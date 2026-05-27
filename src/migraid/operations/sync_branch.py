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
    # Applied django_migrations rows with no file on disk — delete rows directly
    stale_rows: list[tuple[str, str]] = field(default_factory=list)
    # --schema mode: app -> highest tracked migration stem (None = migrate to zero)
    # Only populated for apps whose excess applied migrations still have files on disk.
    schema_targets: dict[str, str | None] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.untracked_files and not self.stale_rows and not self.schema_targets


def build_sync_branch_plan(
    guard: GitGuard,
    app_dirs: list[tuple[str, Path]],
    applied: dict[tuple[str, str], object],
    *,
    schema: bool = False,
) -> SyncBranchPlan:
    """Build the plan for sync-branch.

    Steps:
    1. Find untracked migration .py files via git.
    2. Find (app, stem) keys that are applied but not tracked by git.
    3. For each stale key: if the file is still on disk and --schema is set,
       schedule schema reversal via call_command('migrate'); otherwise schedule
       a direct row deletion.
    """
    untracked_files = guard.untracked_migration_files(app_dirs)
    tracked_keys = guard.tracked_migration_keys(app_dirs)
    app_dir_map = {label: mdir for label, mdir in app_dirs}

    stale_keys = sorted(k for k in applied if k not in tracked_keys)

    schema_targets: dict[str, str | None] = {}
    direct_delete_rows: list[tuple[str, str]] = []

    for app, stem in stale_keys:
        file_on_disk = app in app_dir_map and (app_dir_map[app] / f"{stem}.py").exists()
        if schema and file_on_disk:
            if app not in schema_targets:
                schema_targets[app] = guard.highest_tracked_stem(app_dir_map[app])
        else:
            direct_delete_rows.append((app, stem))

    return SyncBranchPlan(
        untracked_files=untracked_files,
        stale_rows=direct_delete_rows,
        schema_targets=schema_targets,
    )
