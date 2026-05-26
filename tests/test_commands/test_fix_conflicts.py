"""Integration smoke tests for the fix-conflicts subcommand."""

from __future__ import annotations

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_fix_conflicts_no_conflicts() -> None:
    """fix-conflicts on a clean app reports no conflicts and exits normally."""
    call_command(
        "migraid",
        "fix-conflicts",
        "--app",
        "testapp",
        "--dry-run",
        "--allow-applied",
    )


@pytest.mark.django_db
def test_fix_conflicts_algorithm_linearizes(tmp_path) -> None:
    """build_fix_conflicts_plan resolves a two-way conflict."""
    from migraid.analysis.graph import leaf_nodes
    from migraid.analysis.scanner import scan_dirs
    from migraid.operations.plan import build_fix_conflicts_plan
    from tests.conftest import write_migration

    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_branch_a", [("myapp", "0001_initial")])
    write_migration(d, "0002_branch_b", [("myapp", "0001_initial")])

    nodes_before = scan_dirs([("myapp", d)])
    assert len(leaf_nodes(nodes_before, "myapp")) == 2

    plan = build_fix_conflicts_plan(nodes_before, "myapp", d)
    from migraid.operations.plan import PlanExecutor

    PlanExecutor(dry_run=False).apply(plan)

    nodes_after = scan_dirs([("myapp", d)])
    assert len(leaf_nodes(nodes_after, "myapp")) == 1


@pytest.mark.django_db
def test_fix_conflicts_three_way(tmp_path) -> None:
    """Three conflicting leaves are all linearized to a single head."""
    from migraid.analysis.graph import leaf_nodes
    from migraid.analysis.scanner import scan_dirs
    from migraid.operations.plan import PlanExecutor, build_fix_conflicts_plan
    from tests.conftest import write_migration

    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_branch_a", [("myapp", "0001_initial")])
    write_migration(d, "0002_branch_b", [("myapp", "0001_initial")])
    write_migration(d, "0002_branch_c", [("myapp", "0001_initial")])

    nodes_before = scan_dirs([("myapp", d)])
    plan = build_fix_conflicts_plan(nodes_before, "myapp", d)
    PlanExecutor(dry_run=False).apply(plan)

    nodes_after = scan_dirs([("myapp", d)])
    assert len(leaf_nodes(nodes_after, "myapp")) == 1
