"""Integration tests for the prune subcommand."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_prune_dry_run_no_stale_rows(capsys) -> None:
    """prune default dry-run on a fresh DB with no stale rows."""
    call_command("migraid", "prune")
    captured = capsys.readouterr()
    # success() writes to the Rich console → stdout
    assert "stale" in captured.out.lower()


@pytest.mark.django_db(transaction=True)
def test_prune_yes_no_stale_rows(capsys) -> None:
    """prune --yes on a DB with no stale rows reports success."""
    call_command("migraid", "prune", "--yes", "--allow-applied")
    captured = capsys.readouterr()
    assert "stale" in captured.out.lower()


@pytest.mark.django_db(transaction=True)
def test_prune_detects_stale_row() -> None:
    """A row in django_migrations with no matching file is stale."""
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()

    # Insert a fake stale row
    recorder.record_applied("ghostapp", "0099_deleted")

    out = StringIO()
    call_command("migraid", "prune", stdout=out)
    output = out.getvalue()
    assert "ghostapp" in output or "stale" in output.lower()

    # Cleanup
    recorder.record_unapplied("ghostapp", "0099_deleted")
