"""argumentation.py - ASPIC+ graph build and Dung grounded semantics (v3 section 5.3).

Graph model: Argument(id, claim, role, kind). Attacks are a set of (attacker,
attacked) pairs. Attack kinds map to ASPIC+:
  undermine  - attacks a premise (a fact)
  rebuttal   - attacks a conclusion
  undercut   - attacks an inference (rule application)

Grounded extension: standard polynomial greatest fixed-point labeling.
Property-tested against brute-force enumeration of all complete extensions
(uniqueness invariant) in tests/test_argumentation.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from harness_core import Label


class Role(str, Enum):
    PROSECUTION = "PROSECUTION"
    DEFENSE = "DEFENSE"              # affirmative defenses: burden = proponent
    PRECEDENT_UNDERCUT = "PRECEDENT_UNDERCUT"


class AttackKind(str, Enum):
    UNDERMINE = "UNDERMINE"
    REBUTTAL = "REBUTTAL"
    UNDERCUT = "UNDERCUT"


@dataclass
class Argument:
    id: str
    claim: str
    role: Role
    kind: str = "rule"               # "rule" | "premise" | "precedent"
    supported_by_trace: str = ""     # rule/exception id from the evaluation trace
    tier: Optional[str] = None       # load-bearing evidentiary tier, if a premise


@dataclass
class ArgumentGraph:
    arguments: dict[str, Argument] = field(default_factory=dict)
    attacks: set[tuple[str, str]] = field(default_factory=set)  # (attacker, attacked)

    def add(self, arg: Argument) -> None:
        self.arguments[arg.id] = arg

    def attack(self, attacker: str, attacked: str,
               kind: AttackKind = AttackKind.REBUTTAL) -> None:
        if attacker not in self.arguments or attacked not in self.arguments:
            raise ValueError("attack endpoint not in graph")
        self.attacks.add((attacker, attacked))

    def attackers_of(self, arg_id: str) -> list[str]:
        return [a for (a, t) in self.attacks if t == arg_id]

    def label(self) -> dict[str, Label]:
        """Grounded extension labeling (Caminada-style, via Dung's characteristic
        function): S_0 = {}; S_{i+1} = {a : every attacker of a is attacked by
        some member of S_i}. Grounded = least fixed point. Then:
        IN  = member of S;  OUT = attacked by some member of S;
        UNDECIDED = neither. Polynomial, and provably the unique complete
        extension that is a subset of every other complete extension."""
        ids = list(self.arguments)
        s: set[str] = set()
        changed = True
        while changed:
            changed = False
            for aid in ids:
                if aid in s:
                    continue
                attackers = self.attackers_of(aid)
                if not attackers:
                    s.add(aid)
                    changed = True
                    continue
                if all(any((m, att) in self.attacks for m in s)
                       for att in attackers):
                    s.add(aid)
                    changed = True
        labels: dict[str, Label] = {}
        for aid in ids:
            if aid in s:
                labels[aid] = Label.IN
            elif any((m, aid) in self.attacks for m in s):
                labels[aid] = Label.OUT
            else:
                labels[aid] = Label.UNDECIDED
        return labels


def complete_extensions(graph: ArgumentGraph) -> list[set[str]]:
    """Brute-force enumeration of all complete extensions (small graphs only;
    used by property tests to verify grounded-extension uniqueness)."""
    ids = list(graph.arguments)
    n = len(ids)

    def defended_by(ext: frozenset[str], a: str) -> bool:
        # every attacker of a must itself be attacked by some member of ext;
        # an attacker that sits in ext cannot be countered (conflict-free) and
        # therefore defeats defense - it must not be skipped
        for (att, tgt) in graph.attacks:
            if tgt == a:
                if not any((m, att) in graph.attacks for m in ext):
                    return False
        return True

    def is_complete(ext: frozenset[str]) -> bool:
        # conflict-free
        for (a, b) in graph.attacks:
            if a in ext and b in ext:
                return False
        for a in ext:
            if not defended_by(ext, a):
                return False
        for a in ids:
            if a not in ext and defended_by(ext, a):
                return False
        return True

    out = []
    for mask in range(1 << n):
        ext = frozenset(ids[i] for i in range(n) if mask & (1 << i))
        if is_complete(ext):
            out.append(set(ext))
    return out
