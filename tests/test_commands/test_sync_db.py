"""Integration tests for --sync-db on the rename commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.conftest import write_migration


def _setup_gap_app(tmp_path: Path, monkeypatch) -> Path:
    """A 'syncapp' with a numbering gap (0001, 0003) so renumber renames 0003->0002.

    Patches the command's directory lookups and disables the git guard so the
    test never touches the real repo.
    """
    d = tmp_path / "syncapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_step", [("syncapp", "0001_initial")])

    import migraid.management.commands.migraid as cmd

    monkeypatch.setattr(cmd, "_get_app_dirs", lambda app_label=None: [("syncapp", d)])
    monkeypatch.setattr(cmd, "_get_migrations_dir", lambda app: d)
    monkeypatch.setattr(cmd, "_build_guard", lambda force: None)
    return d


def _record(app: str, *names: str):
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()
    for name in names:
        recorder.record_applied(app, name)
    return recorder


@pytest.mark.django_db(transaction=True)
def test_renumber_sync_db_updates_table(tmp_path, monkeypatch) -> None:
    d = _setup_gap_app(tmp_path, monkeypatch)
    recorder = _record("syncapp", "0001_initial", "0003_step")
    migration_model = recorder.Migration
    original_ts = migration_model.objects.get(app="syncapp", name="0003_step").applied

    try:
        # --no-input exercises the alias for --yes.
        call_command("migraid", "renumber", "syncapp", "--sync-db", "--no-input")

        # File renamed on disk.
        assert (d / "0002_step.py").exists()
        assert not (d / "0003_step.py").exists()

        # Row renamed in the table, timestamp preserved.
        assert not migration_model.objects.filter(app="syncapp", name="0003_step").exists()
        synced = migration_model.objects.get(app="syncapp", name="0002_step")
        assert synced.applied == original_ts
        assert migration_model.objects.filter(app="syncapp", name="0001_initial").exists()
    finally:
        migration_model.objects.filter(app="syncapp").delete()
        for leftover in Path.cwd().glob("migraid-syncdb-undo-syncapp-*.sql"):
            leftover.unlink()


@pytest.mark.django_db(transaction=True)
def test_renumber_sync_db_dry_run_writes_nothing(tmp_path, monkeypatch, capsys) -> None:
    d = _setup_gap_app(tmp_path, monkeypatch)
    recorder = _record("syncapp", "0001_initial", "0003_step")
    migration_model = recorder.Migration

    try:
        call_command("migraid", "renumber", "syncapp", "--sync-db", "--dry-run")
        output = capsys.readouterr().out
        # Preview shows the exact SQL...
        assert "UPDATE django_migrations" in output
        # ...but nothing changed on disk or in the table.
        assert (d / "0003_step.py").exists()
        assert migration_model.objects.filter(app="syncapp", name="0003_step").exists()
        assert not list(Path.cwd().glob("migraid-syncdb-undo-syncapp-*.sql"))
    finally:
        migration_model.objects.filter(app="syncapp").delete()


@pytest.mark.django_db(transaction=True)
def test_sync_db_collision_aborts(tmp_path, monkeypatch) -> None:
    d = _setup_gap_app(tmp_path, monkeypatch)
    # Pre-occupy the target name 0002_step so the rename would collide.
    recorder = _record("syncapp", "0001_initial", "0002_step", "0003_step")
    migration_model = recorder.Migration

    try:
        with pytest.raises(CommandError, match="already exists"):
            call_command("migraid", "renumber", "syncapp", "--sync-db", "--no-input")
        # Nothing was renamed on disk.
        assert (d / "0003_step.py").exists()
    finally:
        migration_model.objects.filter(app="syncapp").delete()
        for leftover in Path.cwd().glob("migraid-syncdb-undo-syncapp-*.sql"):
            leftover.unlink()


@pytest.mark.django_db(transaction=True)
def test_sync_db_failure_reverts_files_and_rows(tmp_path, monkeypatch) -> None:
    """A failure during the UPDATE rolls back BOTH the files and the table."""
    import migraid.management.commands.migraid as cmd
    from migraid.operations.table_sync import TableSyncError

    d = _setup_gap_app(tmp_path, monkeypatch)
    recorder = _record("syncapp", "0001_initial", "0003_step")
    migration_model = recorder.Migration

    def boom(*_args, **_kwargs):
        raise TableSyncError("simulated mid-sync failure")

    monkeypatch.setattr(cmd, "execute_table_sync", boom)

    try:
        with pytest.raises(CommandError, match="reverted"):
            call_command("migraid", "renumber", "syncapp", "--sync-db", "--no-input")

        # Files reverted to their original names.
        assert (d / "0003_step.py").exists()
        assert not (d / "0002_step.py").exists()
        # Table untouched; the undo script was cleaned up.
        assert migration_model.objects.filter(app="syncapp", name="0003_step").exists()
        assert not list(Path.cwd().glob("migraid-syncdb-undo-syncapp-*.sql"))
    finally:
        migration_model.objects.filter(app="syncapp").delete()
        for leftover in Path.cwd().glob("migraid-syncdb-undo-syncapp-*.sql"):
            leftover.unlink()
