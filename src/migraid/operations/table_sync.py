"""Sync the django_migrations table when applied migrations are renamed.

Renaming an applied migration file desyncs Django's bookkeeping: the row in
django_migrations still records the old stem, so Django sees the new file as
unapplied and the old name as missing. This module renames those rows in place
(an ``UPDATE`` of the ``name`` column only) so the applied state — including the
original ``applied`` timestamp and the row id — is preserved. Zero data loss.

Squashed migrations need no special handling here: rows are matched by the name
actually recorded in the table, so whether a squash is recorded under its own
name or under replaced originals, the matching rename in ``key_renames`` (the
file side rewrites ``replaces`` in lockstep) keeps both sides consistent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper


class TableSyncCollisionError(Exception):
    """A target migration name already occupies a row in django_migrations."""


class TableSyncError(Exception):
    """An UPDATE affected an unexpected number of rows; the txn must roll back."""


@dataclass
class RowMapping:
    app: str
    old_name: str
    new_name: str
    applied: object | None = None  # original timestamp, preserved across the UPDATE


@dataclass
class RowDeletion:
    app: str
    name: str
    applied: object | None = None  # captured so the undo script can re-INSERT it


@dataclass
class TableSyncPlan:
    mappings: list[RowMapping] = field(default_factory=list)
    # Renamed migrations that had no recorded row (never applied) — nothing to sync.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    # Applied rows whose migration file is being deleted (e.g. dropped merges).
    deletions: list[RowDeletion] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.mappings and not self.deletions


def build_table_sync_plan(
    key_renames: dict[tuple[str, str], tuple[str, str]],
    applied: dict[tuple[str, str], object],
    deleted_keys: set[tuple[str, str]] | None = None,
) -> TableSyncPlan:
    """Map renamed/deleted migrations onto the django_migrations rows to touch.

    Only renames whose *old* key is recorded as applied produce a row mapping;
    the rest are skipped (the file rename alone keeps them consistent). Likewise
    only deleted migrations that are recorded as applied produce a row deletion.

    Raises:
        TableSyncCollisionError: if a target name already names a distinct row
            that will still exist after the sync (an UPDATE would duplicate it).
    """
    vacated = set(key_renames.keys())  # rows whose old name is freed by this sync
    mappings: list[RowMapping] = []
    skipped: list[tuple[str, str]] = []

    for old_key, new_key in sorted(key_renames.items()):
        if old_key not in applied:
            skipped.append(old_key)
            continue
        # Collision: the target name already has a row that is not itself being
        # renamed away in this same sync.
        if new_key in applied and new_key not in vacated:
            raise TableSyncCollisionError(
                f"Cannot rename {old_key[0]}.{old_key[1]} -> {new_key[1]}: a row "
                f"named '{new_key[1]}' already exists in django_migrations for app "
                f"'{new_key[0]}'. Resolve the duplicate before syncing."
            )
        mappings.append(
            RowMapping(
                app=old_key[0],
                old_name=old_key[1],
                new_name=new_key[1],
                applied=_applied_timestamp(applied[old_key]),
            )
        )

    deletions: list[RowDeletion] = []
    for del_key in sorted(deleted_keys or set()):
        if del_key not in applied:
            skipped.append(del_key)
            continue
        deletions.append(
            RowDeletion(
                app=del_key[0],
                name=del_key[1],
                applied=_applied_timestamp(applied[del_key]),
            )
        )

    return TableSyncPlan(mappings=mappings, skipped=skipped, deletions=deletions)


def _applied_timestamp(row: object) -> object | None:
    return getattr(row, "applied", None)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _update_stmt(app: str, from_name: str, to_name: str) -> str:
    return (
        f"UPDATE django_migrations SET name={_quote(to_name)} "
        f"WHERE app={_quote(app)} AND name={_quote(from_name)};"
    )


def _delete_stmt(app: str, name: str) -> str:
    return f"DELETE FROM django_migrations WHERE app={_quote(app)} AND name={_quote(name)};"


def _insert_stmt(app: str, name: str, applied: object | None) -> str:
    if applied is None:
        return f"INSERT INTO django_migrations (app, name) VALUES ({_quote(app)}, {_quote(name)});"
    return (
        "INSERT INTO django_migrations (app, name, applied) VALUES "
        f"({_quote(app)}, {_quote(name)}, {_quote(str(applied))});"
    )


def render_sql(mappings: list[RowMapping], deletions: list[RowDeletion] | None = None) -> list[str]:
    """Forward statements (UPDATE renames, then DELETE removed rows) for preview."""
    lines = [_update_stmt(m.app, m.old_name, m.new_name) for m in mappings]
    lines += [_delete_stmt(d.app, d.name) for d in (deletions or [])]
    return lines


def render_undo_sql(
    mappings: list[RowMapping], deletions: list[RowDeletion] | None = None
) -> list[str]:
    """Reverse statements (revert renames, re-INSERT deleted rows) for the undo script."""
    lines = [_update_stmt(m.app, m.new_name, m.old_name) for m in mappings]
    lines += [_insert_stmt(d.app, d.name, d.applied) for d in (deletions or [])]
    return lines


def write_undo_file(
    mappings: list[RowMapping],
    *,
    deletions: list[RowDeletion] | None = None,
    label: str | None = None,
    directory: Path | None = None,
) -> Path:
    """Write a replayable inverse-SQL script and return its path."""
    base = Path(directory) if directory else Path.cwd()
    suffix = f"-{label}" if label else ""
    path = base / f"migraid-syncdb-undo{suffix}-{int(time.time())}.sql"
    lines = [
        "-- django-migraid sync-db undo script",
        "-- Replay against the same database to restore the previous",
        "-- django_migrations rows (row ids of re-INSERTed rows may differ).",
        "",
        *render_undo_sql(mappings, deletions),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def execute(
    connection: BaseDatabaseWrapper,
    mappings: list[RowMapping],
    deletions: list[RowDeletion] | None = None,
) -> int:
    """Apply row renames then deletions via the ORM, asserting one row each.

    Must be called inside a ``transaction.atomic`` block on the same connection so
    a mismatch (raising TableSyncError) rolls the whole sync back.
    """
    from django.db.migrations.recorder import MigrationRecorder

    migration_model = MigrationRecorder(connection).Migration
    total = 0
    for m in mappings:
        updated = (
            migration_model.objects.using(connection.alias)
            .filter(app=m.app, name=m.old_name)
            .update(name=m.new_name)
        )
        if updated != 1:
            raise TableSyncError(
                f"Expected to update exactly 1 row for {m.app}.{m.old_name} "
                f"-> {m.new_name}, but updated {updated}. Rolling back."
            )
        total += updated
    for d in deletions or []:
        deleted, _ = (
            migration_model.objects.using(connection.alias).filter(app=d.app, name=d.name).delete()
        )
        if deleted != 1:
            raise TableSyncError(
                f"Expected to delete exactly 1 row for {d.app}.{d.name}, "
                f"but deleted {deleted}. Rolling back."
            )
        total += deleted
    return total


def describe_connection(connection: BaseDatabaseWrapper) -> str:
    """Human-readable target DB descriptor for the preview (engine @ host / name)."""
    settings = connection.settings_dict
    engine = (settings.get("ENGINE") or "").rsplit(".", 1)[-1] or "?"
    name = settings.get("NAME") or "?"
    if "sqlite" in engine:
        return f"{engine} / {name}"
    host = settings.get("HOST") or "localhost"
    return f"{engine} @ {host} / {name}"


def record_unapplied(
    connection: BaseDatabaseWrapper,
    app: str,
    name: str,
) -> None:
    """Mark a migration as unapplied in django_migrations."""
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(connection)
    recorder.record_unapplied(app, name)
