"""Tests for the MigrationPlan + PlanExecutor pipeline and plan-building algorithms."""

from __future__ import annotations

from pathlib import Path

import pytest

from migraid.analysis.scanner import MigrationNode, scan_dirs
from migraid.operations.plan import (
    FileRename,
    MigrationPlan,
    PlanExecutor,
    build_fix_conflicts_plan,
    build_rebase_plan,
    build_renumber_plan,
    validate_graph_improved,
)
from tests.conftest import write_migration

# ---------------------------------------------------------------------------
# build_renumber_plan
# ---------------------------------------------------------------------------


def test_build_renumber_plan_with_gap(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_add_field", [("myapp", "0001_initial")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_renumber_plan(nodes, "myapp", d)

    assert not plan.is_empty()
    new_names = {r.new_path.stem for r in plan.renames}
    assert "0002_add_field" in new_names


def test_build_renumber_plan_no_changes(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_step", [("myapp", "0001_initial")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_renumber_plan(nodes, "myapp", d)

    assert plan.is_empty()


def test_build_renumber_plan_updates_internal_deps(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_add_field", [("myapp", "0001_initial")])
    write_migration(d, "0004_add_other", [("myapp", "0003_add_field")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_renumber_plan(nodes, "myapp", d)

    # 0003 → 0002, 0004 → 0003; dep in 0004 should be updated
    new_names = {r.new_path.stem for r in plan.renames}
    assert "0002_add_field" in new_names
    assert "0003_add_other" in new_names


# ---------------------------------------------------------------------------
# build_fix_conflicts_plan
# ---------------------------------------------------------------------------


def test_build_fix_conflicts_plan(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_branch_a", [("myapp", "0001_initial")])
    write_migration(d, "0002_branch_b", [("myapp", "0001_initial")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_fix_conflicts_plan(nodes, "myapp", d)

    assert not plan.is_empty()
    new_names = {r.new_path.stem for r in plan.renames}
    # The alphabetically-later loser should get number 0003
    assert any(name.startswith("0003") for name in new_names)


def test_build_fix_conflicts_plan_no_conflicts(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_step", [("myapp", "0001_initial")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_fix_conflicts_plan(nodes, "myapp", d)

    assert plan.is_empty()


def test_build_fix_conflicts_linearizes_dep(tmp_path: Path) -> None:
    """The loser should be reparented onto the winner, not the shared parent."""
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_branch_a", [("myapp", "0001_initial")])
    write_migration(d, "0002_branch_b", [("myapp", "0001_initial")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_fix_conflicts_plan(nodes, "myapp", d)

    # New content of the renamed loser should reference branch_a (the winner)
    loser_rename = next(r for r in plan.renames if r.new_path.stem.startswith("0003"))
    assert "0002_branch_a" in loser_rename.new_content


# ---------------------------------------------------------------------------
# build_rebase_plan
# ---------------------------------------------------------------------------


def test_build_rebase_plan(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_base_step", [("myapp", "0001_initial")])
    write_migration(d, "0002_local_feat", [("myapp", "0001_initial")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_rebase_plan(
        nodes,
        "myapp",
        d,
        local_names={"0002_local_feat"},
        base_leaf_key=("myapp", "0002_base_step"),
    )

    assert not plan.is_empty()
    new_names = {r.new_path.stem for r in plan.renames}
    assert "0003_local_feat" in new_names


def test_build_rebase_plan_no_local_migrations(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])

    nodes = scan_dirs([("myapp", d)])
    plan = build_rebase_plan(nodes, "myapp", d, local_names=set(), base_leaf_key=None)

    assert plan.is_empty()


def test_build_rebase_plan_reparents_onto_base_leaf(tmp_path: Path) -> None:
    """First local migration's dep on old base should be replaced with base_leaf_key."""
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_main_step", [("myapp", "0001_initial")])
    write_migration(d, "0002_local_feat", [("myapp", "0001_initial")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_rebase_plan(
        nodes,
        "myapp",
        d,
        local_names={"0002_local_feat"},
        base_leaf_key=("myapp", "0002_main_step"),
    )

    renamed = next(r for r in plan.renames if r.new_path.stem == "0003_local_feat")
    # Should depend on 0002_main_step now, not 0001_initial
    assert "0002_main_step" in renamed.new_content


# ---------------------------------------------------------------------------
# PlanExecutor
# ---------------------------------------------------------------------------


def test_plan_executor_apply(tmp_path: Path) -> None:
    src = tmp_path / "0001_initial.py"
    dst = tmp_path / "0002_initial.py"
    src.write_text("# content\n")

    plan = MigrationPlan(
        renames=[FileRename(old_path=src, new_path=dst, new_content="# new content\n")],
        description="test",
    )
    PlanExecutor(dry_run=False).apply(plan)

    assert not src.exists()
    assert dst.read_text() == "# new content\n"


def test_plan_executor_dry_run(tmp_path: Path) -> None:
    src = tmp_path / "0001_initial.py"
    dst = tmp_path / "0002_initial.py"
    src.write_text("# content\n")

    plan = MigrationPlan(
        renames=[FileRename(old_path=src, new_path=dst, new_content="# new\n")],
        description="test",
    )
    PlanExecutor(dry_run=True).apply(plan)

    assert src.exists()  # unchanged
    assert not dst.exists()  # not created


def test_plan_executor_inplace_rewrite(tmp_path: Path) -> None:
    f = tmp_path / "0001_initial.py"
    f.write_text("# old\n")

    plan = MigrationPlan(
        renames=[FileRename(old_path=f, new_path=f, new_content="# new\n")],
        description="test",
    )
    PlanExecutor(dry_run=False).apply(plan)

    assert f.read_text() == "# new\n"


def test_plan_executor_undo_on_failure(tmp_path: Path) -> None:
    """If writing fails mid-plan, the undo log should clean up."""
    src = tmp_path / "0001_initial.py"
    src.write_text("# original\n")
    bad_dst = tmp_path / "nonexistent_dir" / "0002.py"

    plan = MigrationPlan(
        renames=[FileRename(old_path=src, new_path=bad_dst, new_content="# new\n")],
        description="test",
    )
    with pytest.raises(OSError):
        PlanExecutor(dry_run=False).apply(plan)

    # src should still be present (undo reversed the partial writes)
    assert src.exists()


def test_plan_is_empty() -> None:
    assert MigrationPlan().is_empty()
    assert not MigrationPlan(
        renames=[FileRename(Path("/a"), Path("/b"), "x")], description=""
    ).is_empty()


# ---------------------------------------------------------------------------
# validate_graph_improved
# ---------------------------------------------------------------------------


def _node(app: str, name: str, deps: list[tuple[str, str]] | None = None) -> MigrationNode:
    return MigrationNode(
        app_label=app,
        name=name,
        path=Path(f"/fake/{app}/migrations/{name}.py"),
        dependencies=deps or [],
    )


def test_validate_graph_improved_identical_graphs() -> None:
    nodes = {
        ("a", "0001_initial"): _node("a", "0001_initial"),
        ("a", "0002_step"): _node("a", "0002_step", [("a", "0001_initial")]),
    }
    assert validate_graph_improved(nodes, nodes, "a") == []


def test_validate_graph_improved_detects_new_cycle() -> None:
    before = {
        ("a", "0001_initial"): _node("a", "0001_initial"),
        ("a", "0002_step"): _node("a", "0002_step", [("a", "0001_initial")]),
    }
    after = {
        ("a", "0001_initial"): _node("a", "0001_initial", [("a", "0002_step")]),
        ("a", "0002_step"): _node("a", "0002_step", [("a", "0001_initial")]),
    }
    errors = validate_graph_improved(before, after, "a")
    assert len(errors) >= 1
    assert any("cycle" in e.lower() for e in errors)


def test_validate_graph_improved_detects_new_dangling() -> None:
    before = {
        ("a", "0001_initial"): _node("a", "0001_initial"),
        ("a", "0002_step"): _node("a", "0002_step", [("a", "0001_initial")]),
    }
    after = {
        ("a", "0001_initial"): _node("a", "0001_initial"),
        ("a", "0002_step"): _node("a", "0002_step", [("a", "0099_deleted")]),
    }
    errors = validate_graph_improved(before, after, "a")
    assert len(errors) >= 1
    assert any("dangling" in e.lower() for e in errors)
