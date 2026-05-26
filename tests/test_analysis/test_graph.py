"""Tests for DAG graph utilities."""

from __future__ import annotations

from pathlib import Path

from migraid.analysis.graph import (
    cross_app_dependencies,
    dangling_dependencies,
    detect_cycles,
    find_highest_number,
    leaf_nodes,
    root_nodes,
    topological_sort,
)
from migraid.analysis.scanner import MigrationNode


def _node(app: str, name: str, deps: list[tuple[str, str]] | None = None) -> MigrationNode:
    return MigrationNode(
        app_label=app,
        name=name,
        path=Path(f"/fake/{app}/migrations/{name}.py"),
        dependencies=deps or [],
    )


def _nodes(*nodes: MigrationNode) -> dict[tuple[str, str], MigrationNode]:
    return {n.key: n for n in nodes}


# ---- leaf / root ----


def test_leaf_nodes_simple_chain() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_step", [("a", "0001_initial")]),
    )
    leaves = leaf_nodes(nodes, "a")
    assert len(leaves) == 1
    assert leaves[0].name == "0002_step"


def test_root_nodes_simple_chain() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_step", [("a", "0001_initial")]),
    )
    roots = root_nodes(nodes, "a")
    assert len(roots) == 1
    assert roots[0].name == "0001_initial"


def test_leaf_nodes_conflict() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_email", [("a", "0001_initial")]),
        _node("a", "0002_phone", [("a", "0001_initial")]),
    )
    leaves = leaf_nodes(nodes, "a")
    assert len(leaves) == 2
    assert {n.name for n in leaves} == {"0002_email", "0002_phone"}


def test_leaf_nodes_only_own_app() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("b", "0001_initial", [("a", "0001_initial")]),
    )
    # App "a"'s 0001 has a dependent in app "b" but app "a" leaf is 0001
    leaves_a = leaf_nodes(nodes, "a")
    assert len(leaves_a) == 1
    assert leaves_a[0].name == "0001_initial"


# ---- topological_sort ----


def test_topo_sort_linear() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_step", [("a", "0001_initial")]),
        _node("a", "0003_end", [("a", "0002_step")]),
    )
    result = topological_sort(nodes, "a")
    assert [n.name for n in result] == ["0001_initial", "0002_step", "0003_end"]


def test_topo_sort_deterministic_for_parallel() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_email", [("a", "0001_initial")]),
        _node("a", "0002_phone", [("a", "0001_initial")]),
    )
    result = topological_sort(nodes, "a")
    assert result[0].name == "0001_initial"
    # Both 0002 variants come after; order is alphabetical
    names = [n.name for n in result[1:]]
    assert set(names) == {"0002_email", "0002_phone"}
    # Alphabetical tiebreak
    assert names == sorted(names)


def test_topo_sort_empty() -> None:
    assert topological_sort({}, "a") == []


# ---- detect_cycles ----


def test_detect_cycles_no_cycle() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_step", [("a", "0001_initial")]),
    )
    assert detect_cycles(nodes) == []


def test_detect_cycles_self_loop() -> None:
    nodes = _nodes(
        _node("a", "0001_initial", [("a", "0001_initial")]),
    )
    cycles = detect_cycles(nodes)
    assert len(cycles) >= 1


def test_detect_cycles_two_node_cycle() -> None:
    nodes = _nodes(
        _node("a", "0001_initial", [("a", "0002_step")]),
        _node("a", "0002_step", [("a", "0001_initial")]),
    )
    cycles = detect_cycles(nodes)
    assert len(cycles) >= 1


def test_detect_cycles_cross_app() -> None:
    nodes = _nodes(
        _node("a", "0001_initial", [("b", "0001_initial")]),
        _node("b", "0001_initial", [("a", "0001_initial")]),
    )
    cycles = detect_cycles(nodes)
    assert len(cycles) >= 1


# ---- dangling_dependencies ----


def test_dangling_dependencies_clean() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_step", [("a", "0001_initial")]),
    )
    assert dangling_dependencies(nodes) == []


def test_dangling_dependencies_missing_dep() -> None:
    nodes = _nodes(
        _node("a", "0002_step", [("a", "0099_deleted")]),
    )
    result = dangling_dependencies(nodes)
    assert len(result) == 1
    node, dep = result[0]
    assert node.name == "0002_step"
    assert dep == ("a", "0099_deleted")


# ---- find_highest_number ----


def test_find_highest_number() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0003_step"),
        _node("a", "0002_other"),
    )
    assert find_highest_number(nodes, "a") == 3


def test_find_highest_number_exclude() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0003_step"),
    )
    assert find_highest_number(nodes, "a", exclude_keys={("a", "0003_step")}) == 1


def test_find_highest_number_empty() -> None:
    assert find_highest_number({}, "a") == 0


# ---- cross_app_dependencies ----


def test_cross_app_dependencies() -> None:
    nodes = _nodes(
        _node("a", "0001_initial"),
        _node("a", "0002_step", [("a", "0001_initial"), ("b", "0001_initial")]),
        _node("b", "0001_initial"),
    )
    result = cross_app_dependencies(nodes, "a")
    assert ("a", "0002_step") in result
    assert result[("a", "0002_step")] == [("b", "0001_initial")]
    assert ("a", "0001_initial") not in result
