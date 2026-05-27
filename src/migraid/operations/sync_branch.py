"""sync-branch: align local DB and file state to the current git branch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backup import GitGuard


@dataclass
class SyncBranchPlan:
    # Migration .py files on disk not tracked by git (to be deleted)
    untracked_files: list[Path] = field(default_factory=list)
    # Applied rows with no file on disk; only populated when --update-db is given
    stale_rows: list[tuple[str, str]] = field(default_factory=list)
    # --schema mode: app -> highest tracked stem (None = zero); only when --schema
    schema_targets: dict[str, str | None] = field(default_factory=dict)
    # Count of stale rows that exist but were NOT authorized for deletion (no --update-db)
    unauthorized_stale: int = 0

    def is_empty(self) -> bool:
        return not self.untracked_files and not self.stale_rows and not self.schema_targets


def build_sync_branch_plan(
    guard: GitGuard,
    app_dirs: list[tuple[str, Path]],
    applied: dict[tuple[str, str], object],
    *,
    update_db: bool = False,
    schema: bool = False,
) -> SyncBranchPlan:
    """Build the plan for sync-branch.

    File plane is always active: untracked migration .py files are collected.
    DB plane is opt-in:
      - stale_rows populated only when update_db=True
      - schema_targets populated only when schema=True (and file is on disk)
    unauthorized_stale counts rows that would be deleted but aren't authorized,
    so the handler can surface a re-run hint.
    """
    untracked_files = guard.untracked_migration_files(app_dirs)
    tracked_keys = guard.tracked_migration_keys(app_dirs)
    app_dir_map = {label: mdir for label, mdir in app_dirs}

    stale_keys = sorted(k for k in applied if k not in tracked_keys)

    schema_targets: dict[str, str | None] = {}
    stale_rows: list[tuple[str, str]] = []
    unauthorized_stale = 0

    for app, stem in stale_keys:
        file_on_disk = app in app_dir_map and (app_dir_map[app] / f"{stem}.py").exists()
        if schema and file_on_disk:
            if app not in schema_targets:
                schema_targets[app] = guard.highest_tracked_stem(app_dir_map[app])
        elif update_db:
            stale_rows.append((app, stem))
        else:
            unauthorized_stale += 1

    return SyncBranchPlan(
        untracked_files=untracked_files,
        stale_rows=stale_rows,
        schema_targets=schema_targets,
        unauthorized_stale=unauthorized_stale,
    )
