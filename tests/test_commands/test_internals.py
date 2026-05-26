"""Unit tests for management command helper functions and the apply pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import create_autospec, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from migraid.analysis.loader import MigrationAnalyzer
from migraid.management.commands.migraid import (
    _build_guard,
    _safety_check_applied,
)
from tests.conftest import write_migration

# ---------------------------------------------------------------------------
# _build_guard
# ---------------------------------------------------------------------------


def test_build_guard_force_returns_none_when_not_git_repo(tmp_path: Path) -> None:
    """With force=True and no git repo, _build_guard returns None instead of raising."""
    with patch("migraid.management.commands.migraid.GitGuard") as mock_guard_cls:
        from migraid.operations.backup import NotAGitRepoError

        mock_guard_cls.side_effect = NotAGitRepoError("not a repo")
        result = _build_guard(force=True)
        assert result is None


def test_build_guard_no_force_raises_when_not_git_repo(tmp_path: Path) -> None:
    """Without force, NotAGitRepoError becomes CommandError."""
    with patch("migraid.management.commands.migraid.GitGuard") as mock_guard_cls:
        from migraid.operations.backup import NotAGitRepoError

        mock_guard_cls.side_effect = NotAGitRepoError("not a repo")
        with pytest.raises(CommandError, match="Not in a git repository"):
            _build_guard(force=False)


def test_build_guard_dirty_tree_raises_command_error() -> None:
    """DirtyWorkingTreeError is re-raised as CommandError."""
    from migraid.operations.backup import DirtyWorkingTreeError, GitGuard

    with patch("migraid.management.commands.migraid.GitGuard") as mock_guard_cls:
        mock_instance = create_autospec(GitGuard, instance=True)
        mock_guard_cls.return_value = mock_instance
        mock_instance.assert_clean_working_tree.side_effect = DirtyWorkingTreeError(
            "dirty tree"
        )
        with pytest.raises(CommandError, match="dirty tree"):
            _build_guard(force=False)


def test_build_guard_clean_repo_returns_guard() -> None:
    """A clean git repo returns the guard object."""
    from migraid.operations.backup import GitGuard

    with patch("migraid.management.commands.migraid.GitGuard") as mock_guard_cls:
        mock_instance = create_autospec(GitGuard, instance=True)
        mock_guard_cls.return_value = mock_instance
        mock_instance.assert_clean_working_tree.return_value = None

        result = _build_guard(force=False)
        assert result is mock_instance


# ---------------------------------------------------------------------------
# _safety_check_applied
# ---------------------------------------------------------------------------


def test_safety_check_applied_skips_when_allow_applied(tmp_path: Path) -> None:
    """allow_applied=True skips the check entirely."""
    analyzer = MigrationAnalyzer(app_dirs=[])
    _safety_check_applied(analyzer, "myapp", allow_applied=True)  # must not raise


def test_safety_check_applied_skips_when_no_applied(tmp_path: Path) -> None:
    """No applied migrations → no error."""
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])

    analyzer = MigrationAnalyzer(app_dirs=[("myapp", d)], connection=None)
    _safety_check_applied(analyzer, "myapp", allow_applied=False)  # must not raise


@pytest.mark.django_db
def test_safety_check_applied_raises_when_migration_is_applied(tmp_path: Path) -> None:
    """If a migration file exists and is applied, raising CommandError."""
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    d = tmp_path / "blockedapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])

    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()
    recorder.record_applied("blockedapp", "0001_initial")

    try:
        analyzer = MigrationAnalyzer(app_dirs=[("blockedapp", d)], connection=connection)
        with pytest.raises(CommandError, match="applied migration"):
            _safety_check_applied(analyzer, "blockedapp", allow_applied=False)
    finally:
        recorder.record_unapplied("blockedapp", "0001_initial")


# ---------------------------------------------------------------------------
# Full apply path via fix-conflicts command (covers _execute_plan)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fix_conflicts_apply_path_executes_plan(tmp_path: Path) -> None:
    """fix-conflicts --yes --force --allow-applied exercises the full apply pipeline."""
    d = tmp_path / "planapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_branch_a", [("planapp", "0001_initial")])
    write_migration(d, "0002_branch_b", [("planapp", "0001_initial")])

    app_dirs = [("planapp", d)]

    with patch(
        "migraid.management.commands.migraid._get_app_dirs",
        return_value=app_dirs,
    ), patch(
        "migraid.management.commands.migraid._get_migrations_dir",
        return_value=d,
    ):
        # --yes skips confirmation; --force skips git check; --allow-applied skips DB check
        call_command(
            "migraid", "fix-conflicts",
            "--app", "planapp",
            "--yes",
            "--force",
            "--allow-applied",
        )

    from migraid.analysis.graph import leaf_nodes
    from migraid.analysis.scanner import scan_dirs

    nodes = scan_dirs(app_dirs)
    assert len(leaf_nodes(nodes, "planapp")) == 1


@pytest.mark.django_db
def test_renumber_apply_path_executes_plan(tmp_path: Path) -> None:
    """renumber --yes --force --allow-applied exercises the full apply pipeline."""
    d = tmp_path / "renumapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_step", [("renumapp", "0001_initial")])

    app_dirs = [("renumapp", d)]

    with patch(
        "migraid.management.commands.migraid._get_app_dirs",
        return_value=app_dirs,
    ), patch(
        "migraid.management.commands.migraid._get_migrations_dir",
        return_value=d,
    ):
        call_command(
            "migraid", "renumber", "renumapp",
            "--yes",
            "--force",
            "--allow-applied",
        )

    assert (d / "0002_step.py").exists()
    assert not (d / "0003_step.py").exists()
