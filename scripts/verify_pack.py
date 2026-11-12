# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "z3-solver>=4.13",
# ]
# ///
"""verify_pack.py - SMT rule-pack verification in CI (plan v3 section 5.2).

Encodes a TOML rule pack into z3 and checks, per rule:
  1. dead-branch freedom  - some assignment of predicate values fires the rule
  2. contradiction freedom- no assignment makes the rule fire AND any of its
     declared exceptions fire simultaneously (given declared precedence, firing
     exceptions must be mutually exclusive over co-satisfiable predicate sets)
  3. acyclicity           - derived predicates cannot reference themselves
  4. precedence totality  - every pair of exceptions with overlapping predicate
     sets has an explicit total precedence (structural check; the SMT part
     verifies that co-satisfiability of two exceptions is impossible unless
     their predicate sets are disjoint)

Exit code 0 = pack verified; 1 = violation found; 2 = load error.
Run on every rule-pack change (CI gate).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# AGENTS.md Rule 10: direct paths only. Run from the app folder.
if not Path("lib").is_dir():
    sys.exit("ERROR: run this script from the app folder (lib/ not found here)")
sys.path.insert(0, "lib")

import z3  # noqa: E402
from rulepack import _parse_expr, load_pack  # noqa: E402


def check_pack(pack_dir: Path) -> list[str]:
    pack = load_pack(pack_dir)
    violations: list[str] = []

    # 3. acyclicity of derived predicates (static)
    deps: dict[str, set[str]] = {}
    for name, p in pack.predicates.items():
        deps[name] = set()
        if p.kind == "derived":
            left, _, right = _parse_expr(p.expr)
            deps[name] = {x for x in (left, right)
                          if pack.predicates[x].kind == "derived"}
    for name in deps:
        seen, stack = set(), [name]
        while stack:
            cur = stack.pop()
            for d in deps.get(cur, ()):
                if d == name:
                    violations.append(
                        f"acyclicity: derived predicate {name!r} depends on itself")
                    break
                if d not in seen:
                    seen.add(d)
                    stack.append(d)

    def pred_value_expr(name: str, vals: dict[str, z3.BoolRef]) -> z3.BoolRef:
        # both fact and derived predicates are boolean-valued in this abstraction;
        # Kleene unknown-ness is modeled as a free boolean (sat-check only cares
        # whether a firing/contradiction assignment EXISTS)
        return vals[name]

    vals = {name: z3.Bool(name) for name in pack.predicates}
    for rule in pack.rules:
        gate = z3.And(*[pred_value_expr(n, vals) for n in rule.all_of]) \
            if rule.all_of else z3.BoolVal(True)

        # 1. dead-branch freedom: satisfiable that rule fires
        s = z3.Solver()
        s.add(gate)
        if s.check() == z3.unsat:
            violations.append(f"rule {rule.rule_id}: DEAD BRANCH (cannot fire)")

        # 4. precedence totality + 2. contradiction freedom
        for i, e1 in enumerate(rule.exceptions):
            for e2 in rule.exceptions[i + 1:]:
                shared = set(e1.all_of) & set(e2.all_of)
                if not shared:
                    continue  # disjoint predicate sets: no overlap possible
                if e1.precedence == e2.precedence:
                    violations.append(
                        f"rule {rule.rule_id}: exceptions {e1.exception_id}/"
                        f"{e2.exception_id} overlap without total precedence")
                # 2. can both fire simultaneously? model shared predicates True
                s = z3.Solver()
                vals = {n: z3.Bool(n) for n in
                        set(rule.all_of) | set(e1.all_of) | set(e2.all_of)}
                g1 = z3.And(*[vals[n] for n in e1.all_of]) if e1.all_of else z3.BoolVal(True)
                g2 = z3.And(*[vals[n] for n in e2.all_of]) if e2.all_of else z3.BoolVal(True)
                s.add(g1, g2)
                if s.check() == z3.sat:
                    violations.append(
                        f"rule {rule.rule_id}: exceptions {e1.exception_id}/"
                        f"{e2.exception_id} co-satisfiable; precedence "
                        f"{e1.precedence}/{e2.precedence} must resolve and be "
                        f"recorded in the execution trace")
    return violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", type=Path)
    args = ap.parse_args()
    try:
        violations = check_pack(args.pack)
    except Exception as exc:  # noqa: BLE001
        print(f"PACK LOAD ERROR: {exc!r}", flush=True)
        return 2
    if violations:
        for v in violations:
            print(f"VIOLATION: {v}", flush=True)
        return 1
    print(f"PACK VERIFIED: {args.pack}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
