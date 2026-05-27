"""Tests for the linearize subcommand and build_linearize_plan."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.management import call_command

from migraid.analysis.scanner import scan_dirs
from migraid.operations.plan import LinearizeError, PlanExecutor, build_linearize_plan
from tests.conftest import write_migration


def _app(tmp_path: Path, app: str) -> Path:
    d = tmp_path / app / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    return d


def _rename_for(plan, stem: str):
    """Return the FileRename whose old file has this stem, or None."""
    return next((r for r in plan.renames if r.old_path.stem == stem), None)


# ---------------------------------------------------------------------------
# Dependency collapse (the headline behaviour)
# ---------------------------------------------------------------------------


def test_collapses_double_in_app_dependency(tmp_path: Path) -> None:
    """A migration depending on two in-app migrations is reduced to its predecessor."""
    d = _app(tmp_path, "calls")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_b", [("calls", "0001_initial")])
    write_migration(d, "0003_x", [("calls", "0001_initial"), ("calls", "0002_b")])

    nodes = scan_dirs([("calls", d)])
    plan = build_linearize_plan(nodes, "calls", d)

    # Numbering is already correct, so no renames — only a content rewrite.
    assert plan.key_renames == {}
    rename = _rename_for(plan, "0003_x")
    assert rename is not None
    assert "0002_b" in rename.new_content
    assert "0001_initial" not in rename.new_content  # redundant parent dropped


def test_preserves_cross_app_dependency(tmp_path: Path) -> None:
    d = _app(tmp_path, "calls")
    write_migration(d, "0001_initial", [])
    write_migration(
        d,
        "0002_step",
        [("calls", "0001_initial"), ("contacts", "0008_add_phone")],
    )

    nodes = scan_dirs([("calls", d)])
    plan = build_linearize_plan(nodes, "calls", d)

    rename = _rename_for(plan, "0002_step")
    # Already linear in-app and correctly numbered -> only changes if cross-app
    # forced one; here nothing changes, so there is no rename for it.
    assert rename is None
    # Re-run with a redundant in-app dep to confirm cross-app survives a rewrite.
    write_migration(
        d,
        "0003_more",
        [("calls", "0001_initial"), ("calls", "0002_step"), ("contacts", "0008_add_phone")],
    )
    nodes = scan_dirs([("calls", d)])
    plan = build_linearize_plan(nodes, "calls", d)
    rename = _rename_for(plan, "0003_more")
    assert rename is not None
    assert "0002_step" in rename.new_content
    assert "contacts" in rename.new_content  # cross-app preserved
    assert "0001_initial" not in rename.new_content


def test_strip_cross_app_drops_it(tmp_path: Path) -> None:
    d = _app(tmp_path, "calls")
    write_migration(d, "0001_initial", [])
    write_migration(
        d,
        "0002_step",
        [("calls", "0001_initial"), ("contacts", "0008_add_phone")],
    )

    nodes = scan_dirs([("calls", d)])
    plan = build_linearize_plan(nodes, "calls", d, strip_cross_app=True)

    rename = _rename_for(plan, "0002_step")
    assert rename is not None
    assert "contacts" not in rename.new_content


# ---------------------------------------------------------------------------
# Renumbering + forks + merges
# ---------------------------------------------------------------------------


def test_fills_gap_and_chains(tmp_path: Path) -> None:
    d = _app(tmp_path, "gapapp")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0005_later", [("gapapp", "0001_initial")])

    nodes = scan_dirs([("gapapp", d)])
    plan = build_linearize_plan(nodes, "gapapp", d)

    assert plan.key_renames == {("gapapp", "0005_later"): ("gapapp", "0002_later")}


def test_deletes_merge_and_linearizes_fork(tmp_path: Path) -> None:
    d = _app(tmp_path, "myapp")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_a", [("myapp", "0001_initial")])
    write_migration(d, "0002_b", [("myapp", "0001_initial")])
    write_migration(d, "0003_merge", [("myapp", "0002_a"), ("myapp", "0002_b")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_linearize_plan(nodes, "myapp", d)

    assert [p.name for p in plan.deletions] == ["0003_merge.py"]
    assert plan.deleted_keys == [("myapp", "0003_merge")]
    # The fork is linearized: the former sibling now depends on the other branch.
    rename = _rename_for(plan, "0002_b")
    assert rename is not None
    assert rename.new_path.name == "0003_b.py"
    assert "0002_a" in rename.new_content


def test_applies_to_disk(tmp_path: Path) -> None:
    d = _app(tmp_path, "myapp")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_a", [("myapp", "0001_initial")])
    write_migration(d, "0002_b", [("myapp", "0001_initial")])
    write_migration(d, "0003_merge", [("myapp", "0002_a"), ("myapp", "0002_b")])

    nodes = scan_dirs([("myapp", d)])
    plan = build_linearize_plan(nodes, "myapp", d)
    PlanExecutor(dry_run=False).apply(plan)

    on_disk = sorted(p.name for p in d.glob("0*.py"))
    assert on_disk == ["0001_initial.py", "0002_a.py", "0003_b.py"]
    assert not (d / "0003_merge.py").exists()


def test_already_linear_is_noop(tmp_path: Path) -> None:
    d = _app(tmp_path, "linear")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_two", [("linear", "0001_initial")])

    nodes = scan_dirs([("linear", d)])
    plan = build_linearize_plan(nodes, "linear", d)
    assert plan.is_empty()


# ---------------------------------------------------------------------------
# Abort conditions
# ---------------------------------------------------------------------------


def test_aborts_on_merge_with_operations(tmp_path: Path) -> None:
    d = _app(tmp_path, "myapp")
    write_migration(d, "0001_initial", [])
    write_migration(
        d,
        "0002_merge_thing",
        [("myapp", "0001_initial")],
        operations="[migrations.RunPython(migrations.RunPython.noop)]",
    )

    nodes = scan_dirs([("myapp", d)])
    with pytest.raises(LinearizeError, match="has operations"):
        build_linearize_plan(nodes, "myapp", d)


def test_aborts_on_in_app_run_before(tmp_path: Path) -> None:
    d = _app(tmp_path, "rbapp")
    write_migration(d, "0001_initial", [])
    content = """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("rbapp", "0001_initial")]
    run_before = [("rbapp", "0003_later")]
    operations = []
"""
    (d / "0002_step.py").write_text(content)

    nodes = scan_dirs([("rbapp", d)])
    with pytest.raises(LinearizeError, match="run_before"):
        build_linearize_plan(nodes, "rbapp", d)


# ---------------------------------------------------------------------------
# Command integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_command_dry_run_runs() -> None:
    """linearize --dry-run on the (already linear) testapp succeeds."""
    call_command("migraid", "linearize", "--app", "testapp", "--dry-run", "--allow-applied")


@pytest.mark.django_db
def test_command_unknown_app_is_noop() -> None:
    call_command("migraid", "linearize", "--app", "no_such_app", "--dry-run", "--allow-applied")
