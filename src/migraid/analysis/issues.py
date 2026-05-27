"""Issue detectors for django-migraid doctor command."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .graph import dangling_dependencies, detect_cycles, leaf_nodes, topological_sort

if TYPE_CHECKING:
    from .loader import MigrationAnalyzer
    from .scanner import MigrationNode


class Severity(str, Enum):
    ERROR = "error"
    WARN = "warn"
    INFO = "info"


@dataclass
class Issue:
    code: str
    severity: Severity
    app: str
    migration: str | None
    message: str
    hint: str | None = None
    fixable: bool = False
    fix_command: str | None = None


def detect_conflicting_leaves(analyzer: MigrationAnalyzer) -> list[Issue]:
    """E001: multiple leaf nodes in the same app."""
    issues: list[Issue] = []
    apps = {k[0] for k in analyzer.nodes}
    for app in sorted(apps):
        leaves = leaf_nodes(analyzer.nodes, app)
        if len(leaves) > 1:
            names = ", ".join(n.name for n in leaves)
            issues.append(
                Issue(
                    code="E001",
                    severity=Severity.ERROR,
                    app=app,
                    migration=None,
                    message=f"Conflicting leaf migrations: {names}",
                    hint="Run: python manage.py migraid fix-conflicts",
                    fixable=True,
                    fix_command="fix-conflicts",
                )
            )
    return issues


def detect_circular_deps(analyzer: MigrationAnalyzer) -> list[Issue]:
    """E002: circular migration dependencies."""
    issues: list[Issue] = []
    cycles = detect_cycles(analyzer.nodes)
    seen: set[frozenset[tuple[str, str]]] = set()
    for cycle in cycles:
        frozen = frozenset(cycle)
        if frozen in seen:
            continue
        seen.add(frozen)
        cycle_str = " → ".join(f"{a}.{n}" for a, n in cycle)
        first_app = cycle[0][0] if cycle else ""
        issues.append(
            Issue(
                code="E002",
                severity=Severity.ERROR,
                app=first_app,
                migration=cycle[0][1] if cycle else None,
                message=f"Circular dependency: {cycle_str}",
                hint="Break the cycle by splitting one of the cross-app ForeignKey migrations.",
                fixable=False,
            )
        )
    return issues


def detect_numbering_issues(analyzer: MigrationAnalyzer) -> list[Issue]:
    """W006: out-of-order or gap numbering after topological sort."""
    issues: list[Issue] = []
    apps = {k[0] for k in analyzer.nodes}
    for app in sorted(apps):
        sorted_nodes = topological_sort(analyzer.nodes, app)
        for i, node in enumerate(sorted_nodes):
            expected = i + 1
            if node.number != expected:
                issues.append(
                    Issue(
                        code="W006",
                        severity=Severity.WARN,
                        app=app,
                        migration=node.name,
                        message=(
                            f"Migration numbering gap: at position {expected} "
                            f"but has number {node.number} ({node.name})"
                        ),
                        hint=(
                            f"Run: python manage.py migraid renumber {app} to close numbering gaps."
                        ),
                        fixable=True,
                        fix_command="renumber",
                    )
                )
    return issues


def detect_dangling_dependencies(analyzer: MigrationAnalyzer) -> list[Issue]:
    """E004: dependency on a migration that doesn't exist on disk."""
    issues: list[Issue] = []
    for node, dep in dangling_dependencies(analyzer.nodes):
        issues.append(
            Issue(
                code="E004",
                severity=Severity.ERROR,
                app=node.app_label,
                migration=node.name,
                message=f"Depends on missing migration: {dep[0]}.{dep[1]}",
                hint=(
                    "The referenced migration was deleted or never existed. "
                    "Update the dependency to point to the correct migration."
                ),
                fixable=False,
            )
        )
    return issues


def _name_suffix(name: str) -> str:
    m = re.match(r"^\d+_(.*)", name)
    return m.group(1) if m else name


def _renamed_row_suspects(analyzer: MigrationAnalyzer) -> dict[tuple[str, str], MigrationNode]:
    """Map applied rows with no file to the disk migration that looks like the rename.

    Shared by E005 (which reports the desync) and W001 (which must *not* suggest
    pruning such a row — that would delete an applied migration's bookkeeping).
    A suspect is only recorded when exactly one unrecorded disk migration in the
    same app shares the orphan row's name suffix, to avoid false positives.
    """
    try:
        applied = analyzer.applied_migrations()
    except Exception:
        return {}
    disk_keys = set(analyzer.nodes.keys())

    by_suffix: dict[tuple[str, str], list[MigrationNode]] = {}
    for key, node in analyzer.nodes.items():
        if key in applied:
            continue
        by_suffix.setdefault((key[0], node.name_suffix), []).append(node)

    suspects: dict[tuple[str, str], MigrationNode] = {}
    for key in applied:
        if key in disk_keys:
            continue
        candidates = by_suffix.get((key[0], _name_suffix(key[1])))
        if candidates and len(candidates) == 1:
            suspects[key] = candidates[0]
    return suspects


def detect_renamed_applied(analyzer: MigrationAnalyzer) -> list[Issue]:
    """E005: applied row whose file was renamed on disk without syncing the table."""
    issues: list[Issue] = []
    for old_key, node in sorted(_renamed_row_suspects(analyzer).items()):
        issues.append(
            Issue(
                code="E005",
                severity=Severity.ERROR,
                app=old_key[0],
                migration=old_key[1],
                message=(
                    f"django_migrations row '{old_key[0]}.{old_key[1]}' has no file; "
                    f"disk has '{node.name}' (same migration, renamed) — DB is desynced"
                ),
                hint=(
                    "Likely a file-only rename (--allow-applied without --update-db). "
                    "Revert the rename in git and re-run with --update-db, or run: "
                    f"UPDATE django_migrations SET name='{node.name}' "
                    f"WHERE app='{old_key[0]}' AND name='{old_key[1]}';"
                ),
                fixable=False,
            )
        )
    return issues


def detect_stale_db_entries(analyzer: MigrationAnalyzer) -> list[Issue]:
    """W001: django_migrations rows with no corresponding file on disk (DB-dependent)."""
    issues: list[Issue] = []
    try:
        applied = analyzer.applied_migrations()
    except Exception:
        return issues
    disk_keys = set(analyzer.nodes.keys())
    suspects = _renamed_row_suspects(analyzer)
    for key in sorted(applied.keys()):
        if key not in disk_keys and key not in suspects:
            issues.append(
                Issue(
                    code="W001",
                    severity=Severity.WARN,
                    app=key[0],
                    migration=key[1],
                    message=f"Stale django_migrations row: {key[0]}.{key[1]} (no file on disk)",
                    hint="Run: python manage.py migraid prune",
                    fixable=True,
                    fix_command="prune",
                )
            )
    return issues


def detect_missing_reverse_code(analyzer: MigrationAnalyzer) -> list[Issue]:
    """W002: RunPython/RunSQL operations without reverse code."""
    issues: list[Issue] = []
    for node in sorted(analyzer.nodes.values(), key=lambda n: n.key):
        for op in node.operations:
            if op.name in ("RunPython", "RunSQL") and not op.has_reverse:
                kwarg = "reverse_code" if op.name == "RunPython" else "reverse_sql"
                issues.append(
                    Issue(
                        code="W002",
                        severity=Severity.WARN,
                        app=node.app_label,
                        migration=node.name,
                        message=f"{op.name} operation has no {kwarg} — migration is irreversible",
                        hint=(
                            f"Add {kwarg}=migrations.{op.name}.noop to mark as explicitly "
                            "irreversible, or provide a real reverse implementation."
                        ),
                        fixable=False,
                    )
                )
    return issues


def detect_incomplete_squash(analyzer: MigrationAnalyzer) -> list[Issue]:
    """W003: squashed migration with replaced files still present on disk."""
    issues: list[Issue] = []
    disk_keys = set(analyzer.nodes.keys())
    for node in sorted(analyzer.nodes.values(), key=lambda n: n.key):
        if not node.replaces:
            continue
        still_present = [r for r in node.replaces if r in disk_keys]
        if still_present:
            names = ", ".join(f"{a}.{n}" for a, n in still_present[:3])
            issues.append(
                Issue(
                    code="W003",
                    severity=Severity.WARN,
                    app=node.app_label,
                    migration=node.name,
                    message=(
                        f"Squash migration still has replaced files on disk: {names}"
                        + (f" (+{len(still_present) - 3} more)" if len(still_present) > 3 else "")
                    ),
                    hint=(
                        "Complete the squash transition: delete the original migration files "
                        "and remove the `replaces` attribute from the squash migration."
                    ),
                    fixable=False,
                )
            )
    return issues


def detect_merge_migrations(analyzer: MigrationAnalyzer) -> list[Issue]:
    """W004: merge migrations present (bad in rebase-workflow repos)."""
    issues: list[Issue] = []
    for node in sorted(analyzer.nodes.values(), key=lambda n: n.key):
        if node.is_merge_migration and len(node.dependencies) >= 2:
            same_app_deps = [d for d in node.dependencies if d[0] == node.app_label]
            if len(same_app_deps) >= 2:
                issues.append(
                    Issue(
                        code="W004",
                        severity=Severity.WARN,
                        app=node.app_label,
                        migration=node.name,
                        message=(
                            f"Merge migration with {len(same_app_deps)} same-app parents — "
                            "incompatible with rebase workflows"
                        ),
                        hint="Run: python manage.py migraid rebase --base main",
                        fixable=True,
                        fix_command="rebase",
                    )
                )
    return issues


def detect_nondeterministic_deps(analyzer: MigrationAnalyzer) -> list[Issue]:
    """W005: dependencies list not in sorted order."""
    issues: list[Issue] = []
    for node in sorted(analyzer.nodes.values(), key=lambda n: n.key):
        if node.dependencies != sorted(node.dependencies):
            issues.append(
                Issue(
                    code="W005",
                    severity=Severity.WARN,
                    app=node.app_label,
                    migration=node.name,
                    message=(
                        "Dependencies list is not in sorted order"
                        " — can cause non-deterministic diffs"
                    ),
                    hint="Sort the `dependencies` list alphabetically.",
                    fixable=False,
                )
            )
    return issues


def detect_cross_app_risks(analyzer: MigrationAnalyzer) -> list[Issue]:
    """I001: migrations with complex cross-app dependencies."""
    issues: list[Issue] = []
    for node in sorted(analyzer.nodes.values(), key=lambda n: n.key):
        cross = [d for d in node.dependencies if d[0] != node.app_label]
        if len(cross) >= 2:
            apps_referenced = {d[0] for d in cross}
            issues.append(
                Issue(
                    code="I001",
                    severity=Severity.INFO,
                    app=node.app_label,
                    migration=node.name,
                    message=(
                        f"Migration has {len(cross)} cross-app dependencies "
                        f"({', '.join(sorted(apps_referenced))}) — "
                        "complex cross-app deps increase conflict risk"
                    ),
                    fixable=False,
                )
            )
    return issues


def detect_fake_footguns(analyzer: MigrationAnalyzer) -> list[Issue]:
    """I002: heuristic detection of potential --fake footgun patterns."""
    issues: list[Issue] = []
    try:
        applied = analyzer.applied_migrations()
    except Exception:
        return issues
    if not applied:
        return issues

    for key, node in sorted(analyzer.nodes.items()):
        if key not in applied:
            continue
        # Heuristic: non-initial migration with no operations might have been faked
        if not node.initial and not node.operations and not node.replaces:
            issues.append(
                Issue(
                    code="I002",
                    severity=Severity.INFO,
                    app=node.app_label,
                    migration=node.name,
                    message=(
                        "Applied migration has no operations — may have been applied with --fake"
                    ),
                    hint="Verify the database schema matches the expected state.",
                    fixable=False,
                )
            )
    return issues


Detector = Callable[["MigrationAnalyzer"], list[Issue]]

ALL_DETECTORS: list[Detector] = [
    detect_conflicting_leaves,
    detect_circular_deps,
    detect_numbering_issues,
    detect_dangling_dependencies,
    detect_renamed_applied,
    detect_stale_db_entries,
    detect_missing_reverse_code,
    detect_incomplete_squash,
    detect_merge_migrations,
    detect_nondeterministic_deps,
    detect_cross_app_risks,
    detect_fake_footguns,
]

_DB_DEPENDENT: set[Detector] = {
    detect_renamed_applied,
    detect_stale_db_entries,
    detect_fake_footguns,
}


def run_all_detectors(
    analyzer: MigrationAnalyzer,
    *,
    app: str | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    has_db = analyzer.has_db_connection()
    for detector in ALL_DETECTORS:
        if not has_db and detector in _DB_DEPENDENT:
            continue
        issues.extend(detector(analyzer))
    if app:
        issues = [i for i in issues if i.app == app]
    return sorted(issues, key=lambda i: (i.severity.value, i.app, i.migration or ""))
