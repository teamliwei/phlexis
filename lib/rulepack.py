"""rulepack.py - TOML rule pack loading and validation (plan v3 section 5.2).

Pack format (packs/<statute>/pack.toml):

    [meta]
    statute = "RA 4136"
    version = "1.0.0"

    [predicate.speed_exceeds_limit]
    kind = "derived"                      # numeric comparison over number facts
    expr = "recorded_speed > posted_limit"
    required_tier = "DOCUMENTED"

    [predicate.is_authorized_emergency_vehicle]
    kind = "fact"                         # directly grounded boolean fact
    required_tier = "DOCUMENTED"

    [rule.SPEEDING_VIOLATION]
    description = "..."
    all_of = ["speed_exceeds_limit"]
    consequence = "LIABILITY_ESTABLISHED"

    [rule.SPEEDING_VIOLATION.exceptions.emergency_response]
    all_of = ["is_authorized_emergency_vehicle", "is_emergency_response"]
    precedence = 1
    consequence = "IMMUNITY"

Derived predicates with unknown operands evaluate to unknown (Kleene). Numeric
facts come from FactContext.numbers; a comparison with a None operand is unknown.
The loader rejects: unknown predicate references, duplicate precedence within a
rule, packs whose exceptions lack total precedence (checked structurally here;
SMT-level co-satisfiability checks live in scripts/verify_pack.py, z3).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from harness_core import EvidentiaryTier, sha256_bytes


@dataclass
class PredicateDef:
    name: str
    kind: str                       # "fact" | "derived"
    required_tier: EvidentiaryTier
    expr: str = ""                  # for derived: "a > b", "a >= b", ...
    negate: bool = False


@dataclass
class ExceptionDef:
    exception_id: str
    all_of: list[str]
    precedence: int
    consequence: str                # deontic finding, e.g. "IMMUNITY"


@dataclass
class RuleDef:
    rule_id: str
    description: str
    all_of: list[str]
    consequence: str
    exceptions: list[ExceptionDef] = field(default_factory=list)


@dataclass
class RulePack:
    pack_id: str                    # "ra4136" (directory name)
    statute: str
    version: str
    predicates: dict[str, PredicateDef]
    rules: list[RuleDef]
    sha256: str = ""

    def exceptions_of(self, rule_id: str) -> list[ExceptionDef]:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r.exceptions
        return []


# ------------------------------------------------------------- load + validate

_ALLOWED_CMP = (">=", "<=", "==", "!=", ">", "<")


def _parse_expr(expr: str) -> tuple[str, str, str]:
    for op in _ALLOWED_CMP:
        if op in expr:
            left, right = (s.strip() for s in expr.split(op, 1))
            return left, op, right
    raise ValueError(f"derived expr has no comparison operator: {expr!r}")


def load_pack(pack_dir: Path) -> RulePack:
    pack_file = pack_dir / "pack.toml"
    raw = pack_file.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    meta = data["meta"]
    pack_id = pack_dir.name

    predicates: dict[str, PredicateDef] = {}
    for name, p in data.get("predicate", {}).items():
        kind = p.get("kind", "fact")
        if kind not in ("fact", "derived"):
            raise ValueError(f"predicate {name}: bad kind {kind!r}")
        tier = EvidentiaryTier(p.get("required_tier", "ASSERTED"))
        predicates[name] = PredicateDef(
            name=name, kind=kind, required_tier=tier,
            expr=p.get("expr", ""), negate=bool(p.get("negate", False)))

    rules: list[RuleDef] = []
    for rule_id, r in data.get("rule", {}).items():
        exceptions: list[ExceptionDef] = []
        for ex_id, e in r.get("exceptions", {}).items():
            exceptions.append(ExceptionDef(
                exception_id=ex_id, all_of=list(e["all_of"]),
                precedence=int(e["precedence"]),
                consequence=e["consequence"]))
        precs = [e.precedence for e in exceptions]
        if len(precs) != len(set(precs)):
            raise ValueError(f"rule {rule_id}: duplicate exception precedence")
        rules.append(RuleDef(
            rule_id=rule_id, description=r.get("description", ""),
            all_of=list(r["all_of"]), consequence=r["consequence"],
            exceptions=exceptions))

    # referential integrity: every referenced predicate must be declared
    declared = set(predicates)
    for r in rules:
        for pname in r.all_of:
            if pname not in declared:
                raise ValueError(f"rule {r.rule_id}: undeclared predicate {pname!r}")
        for e in r.exceptions:
            for pname in e.all_of:
                if pname not in declared:
                    raise ValueError(
                        f"rule {r.rule_id} exception {e.exception_id}: "
                        f"undeclared predicate {pname!r}")
    for p in predicates.values():
        if p.kind == "derived":
            left, _, right = _parse_expr(p.expr)
            for operand in (left, right):
                if operand not in declared:
                    raise ValueError(
                        f"derived predicate {p.name}: undeclared operand {operand!r}")

    return RulePack(pack_id=pack_id, statute=meta["statute"],
                    version=meta["version"], predicates=predicates, rules=rules,
                    sha256=sha256_bytes(raw))


# ------------------------------------------------------------- fact access

def fact_value(pack: RulePack, ctx, pname: str) -> bool | None:
    """Kleene value of predicate pname given a FactContext."""
    p = pack.predicates[pname]
    if p.kind == "fact":
        return ctx.value_of(pname)
    # derived: numeric comparison; any unknown operand -> unknown
    left, op, right = _parse_expr(p.expr)
    lv = ctx.numbers.get(left)
    rv = ctx.numbers.get(right)
    if lv is None or rv is None:
        return None
    result = {
        ">": lv > rv, ">=": lv >= rv, "<": lv < rv, "<=": lv <= rv,
        "==": lv == rv, "!=": lv != rv,
    }[op]
    return (not result) if p.negate else result


def fact_tier(pack: RulePack, ctx, pname: str):
    rec = ctx.facts.get(pname)
    if rec is not None and rec.tier is not None:
        return rec.tier
    return pack.predicates[pname].required_tier


def fact_prov(pack: RulePack, ctx, pname: str) -> str:
    rec = ctx.facts.get(pname)
    if rec is None:
        return "UNGROUNDED"
    span = rec.quote_span
    return f"{rec.source}:{span[0]}-{span[1]}" if span else rec.source
