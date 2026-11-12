import itertools

from hypothesis import given, settings
from hypothesis import strategies as st

from argumentation import Argument, ArgumentGraph, Label, complete_extensions


def _random_graph(nodes: list[str], edges: list[tuple[str, str]]) -> ArgumentGraph:
    g = ArgumentGraph()
    for n in nodes:
        g.add(Argument(id=n, claim=f"claim {n}", role="PROSECUTION"))
    for (a, b) in edges:
        g.attack(a, b)
    return g


def test_grounded_extension_basic():
    g = _random_graph(["P", "D"], [("D", "P")])
    labels = g.label()
    assert labels["P"] is Label.OUT
    assert labels["D"] is Label.IN


def test_self_defeat_goes_undecided():
    # a <-> b cycle -> both UNDECIDED in grounded extension
    g = _random_graph(["a", "b"], [("a", "b"), ("b", "a")])
    labels = g.label()
    assert labels["a"] is Label.UNDECIDED
    assert labels["b"] is Label.UNDECIDED


def test_unattacked_node_is_in():
    g = _random_graph(["x"], [])
    assert g.label()["x"] is Label.IN


def _brute_force_grounded(g: ArgumentGraph) -> set[str]:
    """Grounded extension = intersection of all complete extensions."""
    from argumentation import complete_extensions
    comps = complete_extensions(g)
    if not comps:
        return set()
    return set.intersection(*comps)


@settings(max_examples=50, deadline=None)
@given(
    st.lists(st.tuples(st.sampled_from(["a", "b", "c", "d", "e"]),
                       st.sampled_from(["a", "b", "c", "d", "e"])),
             max_size=12),
)
def test_grounded_extension_matches_brute_force(edges):
    g = _random_graph(["a", "b", "c", "d", "e"], edges)
    labels = g.label()
    expected = _brute_force_grounded(g)
    got = {aid for aid, lab in labels.items() if lab is Label.IN}
    assert got == expected


@settings(max_examples=50, deadline=None)
@given(
    st.lists(st.tuples(st.sampled_from(["a", "b", "c", "d", "e"]),
                       st.sampled_from(["a", "b", "c", "d", "e"])),
             max_size=12),
)
def test_grounded_extension_unique(edges):
    """Uniqueness invariant: exactly one complete extension equals the
    intersection of all of them (grounded extension is always unique)."""
    g = _random_graph(["a", "b", "c", "d", "e"], edges)
    comps = complete_extensions(g)
    inter = set.intersection(*comps) if comps else set()
    matches = [c for c in comps if c == inter]
    assert len(matches) == 1
