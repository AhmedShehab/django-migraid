"""Integration smoke tests for the renumber subcommand."""

from __future__ import annotations

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_renumber_dry_run_no_changes() -> None:
    """renumber --dry-run on a sequential app reports nothing to do."""
    # testapp has only 0001_initial — already sequential
    call_command("migraid", "renumber", "testapp", "--dry-run", "--allow-applied")


@pytest.mark.django_db
def test_renumber_unknown_app_raises() -> None:
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("migraid", "renumber", "no_such_app", "--dry-run", "--allow-applied")


@pytest.mark.django_db
def test_renumber_algorithm_with_gap(tmp_path) -> None:
    """build_renumber_plan produces correct renames for a gap scenario."""

    from migraid.analysis.scanner import scan_dirs
    from migraid.operations.plan import build_renumber_plan
    from tests.conftest import write_migration

    d = tmp_path / "gapapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_add_field", [("gapapp", "0001_initial")])
    write_migration(d, "0004_add_other", [("gapapp", "0003_add_field")])

    nodes = scan_dirs([("gapapp", d)])
    plan = build_renumber_plan(nodes, "gapapp", d)

    assert not plan.is_empty()
    new_names = {r.new_path.stem for r in plan.renames}
    assert "0002_add_field" in new_names
    assert "0003_add_other" in new_names


@pytest.mark.django_db
def test_renumber_algorithm_applies_to_disk(tmp_path) -> None:
    """PlanExecutor.apply actually renames files."""
    from migraid.analysis.scanner import scan_dirs
    from migraid.operations.plan import PlanExecutor, build_renumber_plan
    from tests.conftest import write_migration

    d = tmp_path / "gapapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_step", [("gapapp", "0001_initial")])

    nodes = scan_dirs([("gapapp", d)])
    plan = build_renumber_plan(nodes, "gapapp", d)

    PlanExecutor(dry_run=False).apply(plan)

    assert (d / "0001_initial.py").exists()
    assert (d / "0002_step.py").exists()
    assert not (d / "0003_step.py").exists()
