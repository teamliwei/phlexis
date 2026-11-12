"""prooffilter.py - structural proof standards and burden mechanics (v3 section 5.3).

Replaces v1's numeric thresholds (a category error) with graph-structural rules:

  preponderance            claim IN, no undefeated rebuttal
  clear_and_convincing     claim IN, zero undefeated undercuts, every load-bearing
                           premise DOCUMENTED or CORROBORATED
  beyond_reasonable_doubt  claim IN and EVERY attack on its support tree strictly
                           OUT (any UNDECIDED in the attacker set defeats it)

Burden asymmetry (single explicit configuration, not post-processing):
  defense_burden = "proponent" - an affirmative-defense argument that ends
  UNDECIDED fails (the accused asserting a defense carries the burden of proof).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from argumentation import ArgumentGraph, Role
from harness_core import Disposition, EvidentiaryTier, Label


@dataclass
class ProofStandard:
    name: str                        # "preponderance" | "clear_and_convincing" |
                                     # "beyond_reasonable_doubt"
    defense_burden: str = "proponent"


@dataclass
class ProofResult:
    satisfied: bool
    reason: str
    defeated_attackers: list[str] = field(default_factory=list)
    undecided_attackers: list[str] = field(default_factory=list)


def _support_tree(graph: ArgumentGraph, root: str) -> set[str]:
    seen: set[str] = set()
    stack = [root]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        # support edges are the reverse of attacks: X supports Y if Y attacks X?
        # No: support is implicit via construction order; the support tree of a
        # claim is the set of arguments attacked by it plus the claim itself
        # (defensive structure). For standard checking we need every argument
        # that attacks the claim's tree - i.e. all attackers of tree members.
        for (a, t) in graph.attacks:
            if t == cur:
                stack.append(a)
    return seen


def check_standard(graph: ArgumentGraph, labels: dict[str, Label],
                   claim_id: str, standard: ProofStandard) -> ProofResult:
    if claim_id not in graph.arguments:
        raise ValueError(f"unknown claim {claim_id!r}")
    if labels.get(claim_id) is not Label.IN:
        if labels.get(claim_id) is Label.UNDECIDED:
            reason = "claim UNDECIDED in grounded extension"
        else:
            reason = "claim OUT in grounded extension"
        return ProofResult(False, reason)

    tree = _support_tree(graph, claim_id)
    defeated: list[str] = []
    undecided: list[str] = []
    for member in tree:
        for att in graph.attackers_of(member):
            lab = labels.get(att, Label.UNDECIDED)
            if lab is Label.OUT:
                defeated.append(att)
            elif lab is Label.UNDECIDED:
                undecided.append(att)

    # defense burden: an undecided DEFENSE argument fails (burden = proponent)
    for member in tree:
        arg = graph.arguments[member]
        if (arg.role is Role.DEFENSE and labels[member] is Label.UNDECIDED
                and standard.defense_burden == "proponent"):
            undecided.append(f"{member} (defense burden unmet)")

    if standard.name == "preponderance":
        # claim IN already means no attacker is IN; undecided attackers are
        # tolerated at this standard (reported as advisory data)
        return ProofResult(True, "preponderance met", defeated, undecided)
    if standard.name == "clear_and_convincing":
        if undecided:
            return ProofResult(False, f"undecided attackers: {undecided}",
                               defeated, undecided)
        low_tier = [m for m in tree
                    if graph.arguments[m].tier == EvidentiaryTier.ASSERTED.value]
        if low_tier:
            return ProofResult(False,
                               f"ASSERTED load-bearing premises: {low_tier}",
                               defeated, undecided)
        return ProofResult(True, "clear and convincing met", defeated, undecided)
    if standard.name == "beyond_reasonable_doubt":
        if undecided:
            return ProofResult(False, f"undecided attacks on support tree: {undecided}",
                               defeated, undecided)
        # every attack on the tree must be strictly OUT (already ensured: no
        # undecided, and IN attackers would have made the claim not-IN)
        return ProofResult(True, "beyond reasonable doubt met", defeated, undecided)
    raise ValueError(f"unknown standard {standard.name!r}")


def disposition(graph: ArgumentGraph, labels: dict[str, Label], claim_id: str,
                standard: ProofStandard,
                primary_unknown: bool) -> tuple[Disposition, str]:
    """Map graph outcome to the final disposition (v2 section 6 STEP 7)."""
    if primary_unknown:
        return (Disposition.INSUFFICIENT_GROUNDING,
                "primary statutory rule evaluated unknown")
    result = check_standard(graph, labels, claim_id, standard)
    if result.satisfied:
        return (Disposition.LIABILITY_ESTABLISHED, result.reason)
    claim = graph.arguments[claim_id]
    # a successful DEFENSE argument negates liability outright
    defense_in = [aid for aid, a in graph.arguments.items()
                  if a.role is Role.DEFENSE and labels.get(aid) is Label.IN]
    if defense_in:
        return (Disposition.IMMUNITY, f"defense IN: {defense_in}")
    return (Disposition.NO_LIABILITY, result.reason)
