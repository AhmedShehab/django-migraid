"""Tests for the sync-branch subcommand and sync_branch operations module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from migraid.operations.sync_branch import SyncBranchPlan, build_sync_branch_plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_guard(
    untracked: list[Path] | None = None,
    tracked_keys: set[tuple[str, str]] | None = None,
    highest_stems: dict[str, str | None] | None = None,
) -> MagicMock:
    guard = MagicMock()
    guard.untracked_migration_files.return_value = untracked or []
    guard.tracked_migration_keys.return_value = tracked_keys or set()
    if highest_stems:

        def _highest(migrations_dir: Path) -> str | None:
            for app_label, stem in (highest_stems or {}).items():
                if app_label in str(migrations_dir):
                    return stem
            return None

        guard.highest_tracked_stem.side_effect = _highest
    else:
        guard.highest_tracked_stem.return_value = None
    return guard


def _record(app: str, *names: str):
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()
    for name in names:
        recorder.record_applied(app, name)
    return recorder


# ---------------------------------------------------------------------------
# Unit tests for build_sync_branch_plan
# ---------------------------------------------------------------------------


def test_plan_empty_when_all_tracked() -> None:
    applied = {("myapp", "0001_initial"): object(), ("myapp", "0002_add_field"): object()}
    tracked = {("myapp", "0001_initial"), ("myapp", "0002_add_field")}
    guard = _make_guard(tracked_keys=tracked)

    plan = build_sync_branch_plan(guard, [("myapp", Path("/fake/myapp/migrations"))], applied)

    assert plan.is_empty()


def test_plan_stale_row_goes_to_unauthorized_without_update_db(tmp_path: Path) -> None:
    """Without update_db, stale rows accumulate in unauthorized_stale, not stale_rows."""
    mdir = tmp_path / "myapp" / "migrations"
    mdir.mkdir(parents=True)

    applied = {("myapp", "0001_initial"): object(), ("myapp", "0002_deleted"): object()}
    tracked = {("myapp", "0001_initial")}
    guard = _make_guard(tracked_keys=tracked)

    plan = build_sync_branch_plan(guard, [("myapp", mdir)], applied)

    assert plan.stale_rows == []
    assert plan.unauthorized_stale == 1


def test_plan_stale_row_when_file_missing_with_update_db(tmp_path: Path) -> None:
    """With update_db=True, stale rows with no file on disk go to stale_rows."""
    mdir = tmp_path / "myapp" / "migrations"
    mdir.mkdir(parents=True)
    (mdir / "0001_initial.py").write_text("")

    applied = {("myapp", "0001_initial"): object(), ("myapp", "0002_deleted"): object()}
    tracked = {("myapp", "0001_initial")}
    guard = _make_guard(tracked_keys=tracked)

    plan = build_sync_branch_plan(guard, [("myapp", mdir)], applied, update_db=True)

    assert ("myapp", "0002_deleted") in plan.stale_rows
    assert plan.schema_targets == {}
    assert plan.unauthorized_stale == 0


def test_plan_schema_mode_file_on_disk(tmp_path: Path) -> None:
    mdir = tmp_path / "myapp" / "migrations"
    mdir.mkdir(parents=True)
    (mdir / "0001_initial.py").write_text("")
    (mdir / "0002_local.py").write_text("")

    applied = {("myapp", "0001_initial"): object(), ("myapp", "0002_local"): object()}
    tracked = {("myapp", "0001_initial")}
    guard = _make_guard(
        tracked_keys=tracked,
        highest_stems={"myapp": "0001_initial"},
    )

    plan = build_sync_branch_plan(guard, [("myapp", mdir)], applied, schema=True)

    assert ("myapp", "0002_local") not in plan.stale_rows
    assert plan.schema_targets.get("myapp") == "0001_initial"
    assert plan.unauthorized_stale == 0


def test_plan_schema_mode_no_file_on_disk_goes_to_unauthorized(tmp_path: Path) -> None:
    """With schema=True but no file on disk, the row is unauthorized (no --update-db)."""
    mdir = tmp_path / "myapp" / "migrations"
    mdir.mkdir(parents=True)

    applied = {("myapp", "0001_initial"): object(), ("myapp", "0002_deleted"): object()}
    tracked = {("myapp", "0001_initial")}
    guard = _make_guard(tracked_keys=tracked)

    plan = build_sync_branch_plan(guard, [("myapp", mdir)], applied, schema=True)

    assert plan.stale_rows == []
    assert "myapp" not in plan.schema_targets
    assert plan.unauthorized_stale == 1


def test_plan_schema_mode_no_file_with_update_db(tmp_path: Path) -> None:
    """schema=True + update_db=True + no file on disk → stale_rows (row delete only)."""
    mdir = tmp_path / "myapp" / "migrations"
    mdir.mkdir(parents=True)

    applied = {("myapp", "0001_initial"): object(), ("myapp", "0002_deleted"): object()}
    tracked = {("myapp", "0001_initial")}
    guard = _make_guard(tracked_keys=tracked)

    plan = build_sync_branch_plan(guard, [("myapp", mdir)], applied, update_db=True, schema=True)

    assert ("myapp", "0002_deleted") in plan.stale_rows
    assert "myapp" not in plan.schema_targets
    assert plan.unauthorized_stale == 0


def test_plan_reports_untracked_files(tmp_path: Path) -> None:
    mdir = tmp_path / "myapp" / "migrations"
    fake = mdir / "0005_local.py"
    untracked = [fake]
    guard = _make_guard(untracked=untracked, tracked_keys=set())

    plan = build_sync_branch_plan(guard, [("myapp", mdir)], {})

    assert plan.untracked_files == untracked


def test_plan_schema_target_none_when_no_tracked_migrations(tmp_path: Path) -> None:
    mdir = tmp_path / "myapp" / "migrations"
    mdir.mkdir(parents=True)
    (mdir / "0001_initial.py").write_text("")

    applied = {("myapp", "0001_initial"): object()}
    tracked: set[tuple[str, str]] = set()
    guard = _make_guard(tracked_keys=tracked, highest_stems={"myapp": None})

    plan = build_sync_branch_plan(guard, [("myapp", mdir)], applied, schema=True)

    assert plan.schema_targets.get("myapp") is None


# ---------------------------------------------------------------------------
# Command integration tests
# ---------------------------------------------------------------------------


def _patch_sync_branch(monkeypatch, plan: SyncBranchPlan) -> None:
    import migraid.management.commands.migraid as cmd

    monkeypatch.setattr(cmd, "build_sync_branch_plan", lambda *a, **kw: plan)


def _patch_guard(monkeypatch) -> None:
    import migraid.management.commands.migraid as cmd

    monkeypatch.setattr(cmd, "GitGuard", lambda: MagicMock())


def _patch_app_dirs(monkeypatch) -> None:
    import migraid.management.commands.migraid as cmd

    monkeypatch.setattr(cmd, "_get_app_dirs", lambda app_label=None: [])


@pytest.mark.django_db
def test_cmd_nothing_to_do(monkeypatch, capsys) -> None:
    _patch_guard(monkeypatch)
    _patch_sync_branch(monkeypatch, SyncBranchPlan())
    _patch_app_dirs(monkeypatch)

    call_command("migraid", "sync-branch", "--yes")

    assert "nothing to do" in capsys.readouterr().out.lower()


@pytest.mark.django_db
def test_cmd_no_git_repo_raises(monkeypatch) -> None:
    import migraid.management.commands.migraid as cmd
    from migraid.operations.backup import NotAGitRepoError

    def _raise():
        raise NotAGitRepoError("no git here")

    monkeypatch.setattr(cmd, "GitGuard", _raise)

    with pytest.raises(CommandError, match="git repository"):
        call_command("migraid", "sync-branch")


@pytest.mark.django_db(transaction=True)
def test_cmd_dry_run_shows_preview_no_changes(monkeypatch, tmp_path, capsys) -> None:
    fake_file = tmp_path / "myapp" / "migrations" / "0002_local.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.write_text("# stub")

    plan = SyncBranchPlan(
        untracked_files=[fake_file],
        stale_rows=[("myapp", "0002_deleted")],
    )
    _patch_guard(monkeypatch)
    _patch_sync_branch(monkeypatch, plan)
    _patch_app_dirs(monkeypatch)

    call_command("migraid", "sync-branch", "--dry-run")

    out = capsys.readouterr().out
    assert "0002_deleted" in out
    assert "0002_local.py" in out
    assert fake_file.exists()


@pytest.mark.django_db(transaction=True)
def test_cmd_default_deletes_files_not_rows(monkeypatch, tmp_path, capsys) -> None:
    """Default sync-branch (no --update-db) deletes untracked files but NOT rows."""
    fake_file = tmp_path / "myapp" / "migrations" / "0002_local.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.write_text("# stub")

    # Simulate plan with files to delete and a stale row hint (unauthorized)
    plan = SyncBranchPlan(
        untracked_files=[fake_file],
        unauthorized_stale=1,
    )
    _patch_guard(monkeypatch)
    _patch_sync_branch(monkeypatch, plan)
    _patch_app_dirs(monkeypatch)

    call_command("migraid", "sync-branch", "--yes")

    out = capsys.readouterr().out
    # File was deleted
    assert not fake_file.exists()
    # Hint about --update-db was shown
    assert "--update-db" in out


@pytest.mark.django_db(transaction=True)
def test_cmd_update_db_deletes_stale_rows_and_files(monkeypatch, tmp_path) -> None:
    """--update-db deletes stale rows and untracked files."""
    recorder = _record("branchapp", "0002_feature")

    fake_file = tmp_path / "branchapp" / "migrations" / "0002_feature.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.write_text("# stub")

    plan = SyncBranchPlan(
        untracked_files=[fake_file],
        stale_rows=[("branchapp", "0002_feature")],
    )
    _patch_guard(monkeypatch)
    _patch_sync_branch(monkeypatch, plan)
    _patch_app_dirs(monkeypatch)

    try:
        call_command("migraid", "sync-branch", "--update-db", "--yes")

        assert not fake_file.exists()
        assert not recorder.Migration.objects.filter(
            app="branchapp", name="0002_feature"
        ).exists()
    finally:
        recorder.Migration.objects.filter(app="branchapp").delete()


@pytest.mark.django_db(transaction=True)
def test_cmd_schema_calls_migrate(monkeypatch) -> None:
    plan = SyncBranchPlan(schema_targets={"myapp": "0001_initial"})
    _patch_guard(monkeypatch)
    _patch_sync_branch(monkeypatch, plan)
    _patch_app_dirs(monkeypatch)

    with patch("django.core.management.call_command") as mock_cc:
        call_command("migraid", "sync-branch", "--yes", "--schema")
        schema_calls = [c for c in mock_cc.call_args_list if c.args and c.args[0] == "migrate"]
        assert any("myapp" in str(c) for c in schema_calls)


@pytest.mark.django_db(transaction=True)
def test_cmd_schema_target_zero(monkeypatch) -> None:
    plan = SyncBranchPlan(schema_targets={"myapp": None})
    _patch_guard(monkeypatch)
    _patch_sync_branch(monkeypatch, plan)
    _patch_app_dirs(monkeypatch)

    with patch("django.core.management.call_command") as mock_cc:
        call_command("migraid", "sync-branch", "--yes", "--schema")
        schema_calls = [c for c in mock_cc.call_args_list if c.args and c.args[0] == "migrate"]
        assert any("zero" in str(c) for c in schema_calls)


@pytest.mark.django_db(transaction=True)
def test_cmd_aborts_on_no_confirm(monkeypatch, capsys) -> None:
    plan = SyncBranchPlan(stale_rows=[("myapp", "0001_initial")])
    _patch_guard(monkeypatch)
    _patch_sync_branch(monkeypatch, plan)
    _patch_app_dirs(monkeypatch)

    with patch("builtins.input", return_value="n"):
        call_command("migraid", "sync-branch")

    out = capsys.readouterr().out
    assert "aborted" in out.lower()
