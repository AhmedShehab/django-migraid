"""Tier 2: MigrationAnalyzer facade combining static scan with optional live Django loader."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .scanner import MigrationNode, scan_dirs

if TYPE_CHECKING:
    pass


class MigrationAnalyzer:
    """Facade over Tier-1 (static) and Tier-2 (live Django loader) analysis.

    The static scan works on any directory without importing migration modules.
    The live loader is used only for DB-dependent checks (W001, I002) and is
    constructed inside a try/except so a broken graph doesn't prevent diagnosis.
    """

    def __init__(
        self,
        app_dirs: list[tuple[str, Path]],
        connection: object | None = None,
    ) -> None:
        self._app_dirs = app_dirs
        self._connection = connection
        self._nodes: dict[tuple[str, str], MigrationNode] | None = None
        self._applied: dict[tuple[str, str], object] | None = None
        self.live_load_error: Exception | None = None

    @property
    def nodes(self) -> dict[tuple[str, str], MigrationNode]:
        if self._nodes is None:
            self._nodes = scan_dirs(self._app_dirs)
        return self._nodes

    def reload(self) -> None:
        self._nodes = None
        self._applied = None
        self.live_load_error = None

    def has_db_connection(self) -> bool:
        return self._connection is not None

    def applied_migrations(self) -> dict[tuple[str, str], object]:
        if self._connection is None:
            return {}
        if self._applied is not None:
            return self._applied
        try:
            from django.db.migrations.recorder import MigrationRecorder

            recorder = MigrationRecorder(self._connection)
            self._applied = dict(recorder.applied_migrations())
        except Exception as exc:
            self.live_load_error = exc
            self._applied = {}
        return self._applied if self._applied is not None else {}
