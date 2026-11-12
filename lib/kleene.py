"""kleene.py - three-valued statutory evaluation (plan v3 section 5.2).

Predicates evaluate over {True, False, None(=unknown)} with Kleene logic:
    unknown AND false = false;  unknown AND true = unknown;  NOT unknown = unknown.
Consequences (v2 section 3.4.3, carried over):
  - primary rule unknown  -> INSUFFICIENT_GROUNDING (never "not liable")
  - exception unknown     -> exception not fired; graph may still carry the claim
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from harness_core import Disposition


# ------------------------------------------------------------- Kleene tables

def k_and(a: Optional[bool], b: Optional[bool]) -> Optional[bool]:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def k_or(a: Optional[bool], b: Optional[bool]) -> Optional[bool]:
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def k_not(a: Optional[bool]) -> Optional[bool]:
    return None if a is None else (not a)


# ------------------------------------------------------------- evaluation

@dataclass
class PredicateOutcome:
    name: str
    value: Optional[bool]
    tier: Optional[str] = None       # evidentiary tier of the grounding fact
    provenance: str = ""             # quote span / source of the grounding fact
    derived_from: list[str] = field(default_factory=list)


@dataclass
class RuleOutcome:
    rule_id: str
    description: str = ""
    predicates: list[PredicateOutcome] = field(default_factory=list)
    gate: Optional[bool] = None      # Kleene conjunction of predicate values
    exceptions: list["ExceptionOutcome"] = field(default_factory=list)
    finding: str = ""                # deontic finding id, or INSUFFICIENT_GROUNDING


@dataclass
class ExceptionOutcome:
    exception_id: str
    gate: Optional[bool]
    fired: bool                      # True only when gate is True (unknown never fires)
    predicates: list[PredicateOutcome] = field(default_factory=list)


@dataclass
class EvaluationTrace:
    """The sole substrate of the argument graph: nothing in the graph may assert
    a rule outcome absent from this trace."""
    pack_id: str
    pack_sha256: str
    rule_outcomes: list[RuleOutcome] = field(default_factory=list)
    ungrounded_predicates: list[str] = field(default_factory=list)

    def findings(self) -> list[str]:
        return [ro.finding for ro in self.rule_outcomes if ro.finding]

    def primary_unknown(self) -> bool:
        return any(ro.gate is None for ro in self.rule_outcomes)


def _eval_predicate(name: str, fact_value: Optional[bool], tier,
                    provenance: str) -> PredicateOutcome:
    tier_s = None if tier is None else getattr(tier, "value", str(tier))
    return PredicateOutcome(name=name, value=fact_value, tier=tier_s,
                            provenance=provenance)


def evaluate_rule(rule, fact_value, fact_tier, fact_prov, exceptions) -> RuleOutcome:
    """Evaluate one rule against fact values.

    fact_value: callable predicate_name -> Optional[bool]
    fact_tier / fact_prov: callables predicate_name -> tier / provenance
    exceptions: iterable of (exception_def, fact_value, fact_tier, fact_prov)
    """
    outs: list[PredicateOutcome] = []
    for pname in rule.all_of:
        outs.append(_eval_predicate(pname, fact_value(pname),
                                    fact_tier(pname), fact_prov(pname)))
    gate: Optional[bool] = True
    for o in outs:
        gate = k_and(gate, o.value)

    ex_outs: list[ExceptionOutcome] = []
    for ex in sorted(exceptions, key=lambda e: e.precedence):
        ex_gate: Optional[bool] = True
        ex_preds: list[PredicateOutcome] = []
        for pname in ex.all_of:
            po = _eval_predicate(pname, fact_value(pname),
                                 fact_tier(pname), fact_prov(pname))
            ex_preds.append(po)
            ex_gate = k_and(ex_gate, po.value)
        ex_outs.append(ExceptionOutcome(exception_id=ex.exception_id, gate=ex_gate,
                                        fired=(ex_gate is True),
                                        predicates=ex_preds))

    outcome = RuleOutcome(rule_id=rule.rule_id, description=rule.description,
                          predicates=outs, gate=gate, exceptions=ex_outs)

    fired_exception = next((e for e in ex_outs if e.fired), None)
    if gate is None:
        outcome.finding = Disposition.INSUFFICIENT_GROUNDING.value
    elif fired_exception is not None:
        outcome.finding = fired_exception.exception_id  # deontic consequence id
    elif gate is True:
        outcome.finding = rule.consequence
    else:
        outcome.finding = ""  # rule simply does not fire
    return outcome
