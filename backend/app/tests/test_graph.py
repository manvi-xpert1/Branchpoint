import pytest

from app.models import Component, Dependency, System, ValidationError
from app.simulation.graph import DependencyGraph


def chain_system(*ids: str, cycle: bool = False) -> System:
    """ids[0] depends on ids[1], which depends on ids[2], ..."""
    s = System(id="t", name="t")
    for cid in ids:
        s.add_component(Component(cid, cid, "service"))
    for a, b in zip(ids, ids[1:]):
        s.add_dependency(Dependency(f"{a}->{b}", a, b))
    if cycle:
        s.add_dependency(Dependency(f"{ids[-1]}->{ids[0]}", ids[-1], ids[0]))
    return s


def test_impact_bfs_finds_all_dependents_with_distances():
    g = DependencyGraph(chain_system("a", "b", "c"))
    assert g.impact_bfs("c") == {"c": 0, "b": 1, "a": 2}
    assert g.impact_bfs("a") == {"a": 0}


def test_topological_order_puts_dependencies_first():
    order = DependencyGraph(chain_system("a", "b", "c")).topological_order()
    assert order.index("c") < order.index("b") < order.index("a")


def test_cycle_detection():
    assert DependencyGraph(chain_system("a", "b", "c")).find_cycle() is None
    cycle = DependencyGraph(chain_system("a", "b", "c", cycle=True)).find_cycle()
    assert cycle is not None and cycle[0] == cycle[-1] and set(cycle) == {"a", "b", "c"}


def test_topological_order_rejects_cycles():
    with pytest.raises(ValueError, match="cycle"):
        DependencyGraph(chain_system("a", "b", cycle=True)).topological_order()


def test_validation_catches_unknown_and_self_references():
    s = chain_system("a", "b")
    s.add_dependency(Dependency("bad", "a", "ghost"))
    s.add_dependency(Dependency("self", "b", "b"))
    with pytest.raises(ValidationError) as exc:
        s.validate()
    assert "ghost" in str(exc.value) and "itself" in str(exc.value)


def test_invalid_dependency_type_rejected():
    with pytest.raises(ValueError):
        Dependency("x", "a", "b", dependency_type="sometimes")
