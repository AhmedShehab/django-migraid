"""Integration tests for the prune subcommand."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_prune_dry_run_no_stale_rows(capsys) -> None:
    """prune --dry-run on a fresh DB with no stale rows reports success."""
    call_command("migraid", "prune", "--dry-run")
    captured = capsys.readouterr()
    assert "stale" in captured.out.lower()


@pytest.mark.django_db(transaction=True)
def test_prune_yes_no_stale_rows(capsys) -> None:
    """prune --yes on a DB with no stale rows reports success."""
    call_command("migraid", "prune", "--yes", "--allow-remote-db")
    captured = capsys.readouterr()
    assert "stale" in captured.out.lower()


@pytest.mark.django_db(transaction=True)
def test_prune_noinput_no_stale_rows(capsys) -> None:
    """prune --noinput is an alias for --yes."""
    call_command("migraid", "prune", "--noinput", "--allow-remote-db")
    captured = capsys.readouterr()
    assert "stale" in captured.out.lower()


@pytest.mark.django_db(transaction=True)
def test_prune_default_previews_and_prompts(monkeypatch, capsys) -> None:
    """Bare prune (no --dry-run, no --yes) previews and confirms before deleting."""
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()
    recorder.record_applied("ghostapp2", "0099_deleted")

    try:
        # Simulate user typing "n" — nothing should be deleted
        with patch("builtins.input", return_value="n"):
            call_command("migraid", "prune")
        out = capsys.readouterr().out
        assert "ghostapp2" in out or "stale" in out.lower()
        # Row still exists because user said "n"
        assert recorder.Migration.objects.filter(app="ghostapp2", name="0099_deleted").exists()
    finally:
        recorder.record_unapplied("ghostapp2", "0099_deleted")


@pytest.mark.django_db(transaction=True)
def test_prune_detects_stale_row() -> None:
    """A row in django_migrations with no matching file is stale."""
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()
    recorder.record_applied("ghostapp", "0099_deleted")

    out = StringIO()
    call_command("migraid", "prune", stdout=out)
    output = out.getvalue()
    assert "ghostapp" in output or "stale" in output.lower()

    # Cleanup
    recorder.record_unapplied("ghostapp", "0099_deleted")


@pytest.mark.django_db(transaction=True)
def test_prune_allow_remote_db_flag_accepted() -> None:
    """--allow-remote-db is accepted without error."""
    call_command("migraid", "prune", "--yes", "--allow-remote-db")


@pytest.mark.django_db(transaction=True)
def test_prune_allow_applied_flag_rejected() -> None:
    """--allow-applied is no longer a valid prune flag."""
    with pytest.raises((CommandError, SystemExit)):
        call_command("migraid", "prune", "--allow-applied")
