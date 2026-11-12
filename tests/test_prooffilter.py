import pytest

from argumentation import Argument, ArgumentGraph, Label, Role
from harness_core import Disposition, EvidentiaryTier
from prooffilter import ProofStandard, check_standard, disposition


def _graph_defense_in():
    """Prosecution claim attacked by a winning defense argument."""
    g = ArgumentGraph()
    g.add(Argument(id="P", claim="speeding", role=Role.PROSECUTION))
    g.add(Argument(id="D", claim="emergency response", role=Role.DEFENSE,
                   tier=EvidentiaryTier.DOCUMENTED.value))
    g.attack("D", "P")
    return g, g.label()


def test_beyond_doubt_vs_undecided_claim():
    """A claim with a cycle-backed attacker is UNDECIDED in grounded semantics
    and can never satisfy beyond-reasonable-doubt (any UNDECIDED defeats it)."""
    g = ArgumentGraph()
    g.add(Argument(id="P", claim="speeding", role=Role.PROSECUTION))
    g.add(Argument(id="U", claim="undercut", role=Role.PRECEDENT_UNDERCUT))
    g.add(Argument(id="X", claim="x", role=Role.PRECEDENT_UNDERCUT))
    g.add(Argument(id="Y", claim="y", role=Role.PRECEDENT_UNDERCUT))
    g.attack("U", "P")
    g.attack("X", "U")
    g.attack("Y", "X")
    g.attack("X", "Y")
    labels = g.label()
    assert labels["P"] is Label.UNDECIDED  # attacker U is UNDECIDED (cycle)
    res = check_standard(g, labels, "P", ProofStandard("beyond_reasonable_doubt"))
    assert not res.satisfied


def test_beyond_doubt_passes_clean():
    g = ArgumentGraph()
    g.add(Argument(id="P", claim="speeding", role=Role.PROSECUTION))
    labels = g.label()
    res = check_standard(g, labels, "P", ProofStandard("beyond_reasonable_doubt"))
    assert res.satisfied


def test_clear_convincing_rejects_asserted_premise():
    g = ArgumentGraph()
    g.add(Argument(id="P", claim="speeding", role=Role.PROSECUTION,
                   tier=EvidentiaryTier.ASSERTED.value))
    labels = g.label()
    res = check_standard(g, labels, "P", ProofStandard("clear_and_convincing"))
    assert not res.satisfied
    res2 = check_standard(g, labels, "P", ProofStandard("preponderance"))
    assert res2.satisfied


def test_defense_in_gives_immunity():
    g, labels = _graph_defense_in()
    disp, why = disposition(g, labels, "P", ProofStandard("preponderance"),
                            primary_unknown=False)
    assert disp is Disposition.IMMUNITY


def test_primary_unknown_is_insufficient_grounding():
    g = ArgumentGraph()
    g.add(Argument(id="P", claim="speeding", role=Role.PROSECUTION))
    labels = g.label()
    disp, why = disposition(g, labels, "P", ProofStandard("beyond_reasonable_doubt"),
                            primary_unknown=True)
    assert disp is Disposition.INSUFFICIENT_GROUNDING
