"""Unit tests for the django_migrations table-sync operations."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from migraid.operations.table_sync import (
    RowMapping,
    TableSyncCollisionError,
    TableSyncError,
    build_table_sync_plan,
    describe_connection,
    execute,
    render_sql,
    render_undo_sql,
    write_undo_file,
)


def _applied(*keys: tuple[str, str], ts: str = "2026-01-02") -> dict:
    return {k: SimpleNamespace(applied=ts) for k in keys}


# ---------------------------------------------------------------------------
# build_table_sync_plan
# ---------------------------------------------------------------------------


def test_build_maps_applied_rows() -> None:
    renames = {("app", "0005_foo"): ("app", "0008_foo")}
    plan = build_table_sync_plan(renames, _applied(("app", "0005_foo")))
    assert len(plan.mappings) == 1
    m = plan.mappings[0]
    assert (m.app, m.old_name, m.new_name) == ("app", "0005_foo", "0008_foo")
    assert m.applied == "2026-01-02"
    assert plan.skipped == []


def test_build_skips_unapplied_renames() -> None:
    renames = {("app", "0005_foo"): ("app", "0008_foo")}
    plan = build_table_sync_plan(renames, _applied())  # nothing applied
    assert plan.is_empty()
    assert plan.skipped == [("app", "0005_foo")]


def test_build_collision_raises() -> None:
    renames = {("app", "0005_foo"): ("app", "0008_foo")}
    applied = _applied(("app", "0005_foo"), ("app", "0008_foo"))
    with pytest.raises(TableSyncCollisionError):
        build_table_sync_plan(renames, applied)


def test_build_collision_allows_swap() -> None:
    """If the target name is itself being renamed away, it is not a collision."""
    renames = {
        ("app", "0005_a"): ("app", "0006_a"),
        ("app", "0006_b"): ("app", "0007_b"),
    }
    applied = _applied(("app", "0005_a"), ("app", "0006_b"))
    plan = build_table_sync_plan(renames, applied)
    assert len(plan.mappings) == 2


# ---------------------------------------------------------------------------
# SQL rendering + undo file
# ---------------------------------------------------------------------------


def test_render_sql_forward_and_undo() -> None:
    mappings = [RowMapping(app="app", old_name="0005_foo", new_name="0008_foo")]
    fwd = render_sql(mappings)[0]
    assert fwd == (
        "UPDATE django_migrations SET name='0008_foo' WHERE app='app' AND name='0005_foo';"
    )
    undo = render_undo_sql(mappings)[0]
    assert undo == (
        "UPDATE django_migrations SET name='0005_foo' WHERE app='app' AND name='0008_foo';"
    )


def test_render_sql_escapes_quotes() -> None:
    mappings = [RowMapping(app="ap'p", old_name="o", new_name="n")]
    assert "ap''p" in render_sql(mappings)[0]


def test_write_undo_file(tmp_path) -> None:
    mappings = [RowMapping(app="app", old_name="0005_foo", new_name="0008_foo")]
    path = write_undo_file(mappings, label="app", directory=tmp_path)
    assert path.exists()
    text = path.read_text()
    # Undo restores the OLD name.
    assert "SET name='0005_foo'" in text
    assert path.name.startswith("migraid-syncdb-undo-app-")


# ---------------------------------------------------------------------------
# describe_connection
# ---------------------------------------------------------------------------


def test_describe_connection_sqlite() -> None:
    conn = SimpleNamespace(
        settings_dict={"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    )
    assert describe_connection(conn) == "sqlite3 / :memory:"


def test_describe_connection_postgres() -> None:
    conn = SimpleNamespace(
        settings_dict={
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "appdb",
            "HOST": "db.prod.internal",
        }
    )
    assert describe_connection(conn) == "postgresql @ db.prod.internal / appdb"


# ---------------------------------------------------------------------------
# execute (needs a real DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_execute_renames_row_preserving_timestamp() -> None:
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()
    recorder.record_applied("syncapp", "0005_foo")
    migration_model = recorder.Migration
    before = migration_model.objects.get(app="syncapp", name="0005_foo")
    original_ts = before.applied
    original_pk = before.pk

    try:
        count = execute(connection, [RowMapping("syncapp", "0005_foo", "0008_foo")])
        assert count == 1
        assert not migration_model.objects.filter(app="syncapp", name="0005_foo").exists()
        after = migration_model.objects.get(app="syncapp", name="0008_foo")
        assert after.applied == original_ts  # timestamp preserved
        assert after.pk == original_pk  # same row, not delete+insert
    finally:
        migration_model.objects.filter(app="syncapp").delete()


@pytest.mark.django_db(transaction=True)
def test_execute_row_count_mismatch_raises() -> None:
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder

    MigrationRecorder(connection).ensure_schema()
    with pytest.raises(TableSyncError):
        execute(connection, [RowMapping("ghost", "0001_missing", "0002_missing")])
