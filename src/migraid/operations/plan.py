"""Plan → Preview → Apply pipeline with undo log and post-apply validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..analysis.graph import (
    dangling_dependencies,
    detect_cycles,
    find_highest_number,
    leaf_nodes,
    topological_sort,
)
from ..analysis.scanner import MigrationNode
from .rewriter import rewrite_dependencies

if TYPE_CHECKING:
    from ..output.console import ConsoleOutput


@dataclass
class FileRename:
    old_path: Path
    new_path: Path
    new_content: str


@dataclass
class MigrationPlan:
    renames: list[FileRename] = field(default_factory=list)
    description: str = ""

    def is_empty(self) -> bool:
        return not self.renames


class PlanExecutor:
    def __init__(
        self,
        dry_run: bool = False,
        output: ConsoleOutput | None = None,
    ) -> None:
        self.dry_run = dry_run
        self._output = output

    def preview(self, plan: MigrationPlan) -> None:
        if self._output is None:
            return
        for rename in plan.renames:
            old_content = (
                rename.old_path.read_text(encoding="utf-8") if rename.old_path.exists() else ""
            )
            self._output.print_diff(old_content, rename.new_content, rename.old_path.name)

    def apply(self, plan: MigrationPlan) -> None:
        if self.dry_run:
            self.preview(plan)
            return

        undo_log: list[tuple[str, Path, str | None]] = []

        try:
            # Phase 1: write new files
            for rename in plan.renames:
                if rename.new_path.exists() and rename.new_path != rename.old_path:
                    orig = rename.new_path.read_text(encoding="utf-8")
                    rename.new_path.write_text(rename.new_content, encoding="utf-8")
                    undo_log.append(("overwritten", rename.new_path, orig))
                elif rename.new_path != rename.old_path:
                    rename.new_path.write_text(rename.new_content, encoding="utf-8")
                    undo_log.append(("created", rename.new_path, None))
                else:
                    # Same path — in-place rewrite
                    orig = (
                        rename.old_path.read_text(encoding="utf-8")
                        if rename.old_path.exists()
                        else None
                    )
                    rename.new_path.write_text(rename.new_content, encoding="utf-8")
                    undo_log.append(("overwritten", rename.new_path, orig))

            # Phase 2: delete old files (only when path changed)
            for rename in plan.renames:
                if rename.old_path != rename.new_path and rename.old_path.exists():
                    orig = rename.old_path.read_text(encoding="utf-8")
                    rename.old_path.unlink()
                    undo_log.append(("deleted", rename.old_path, orig))

        except Exception:
            self._undo(undo_log)
            raise

    def _undo(self, undo_log: list[tuple[str, Path, str | None]]) -> None:
        for op, path, content in reversed(undo_log):
            try:
                if op == "created":
                    path.unlink(missing_ok=True)
                elif op in ("deleted", "overwritten") and content is not None:
                    path.write_text(content, encoding="utf-8")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Algorithm helpers
# ---------------------------------------------------------------------------

def _build_rename_map_for_renumber(
    nodes: dict[tuple[str, str], MigrationNode],
    app: str,
) -> dict[tuple[str, str], tuple[str, str]]:
    sorted_nodes = topological_sort(nodes, app)
    rename_map: dict[tuple[str, str], tuple[str, str]] = {}
    for i, node in enumerate(sorted_nodes):
        expected = i + 1
        if node.number != expected:
            new_name = f"{expected:04d}_{node.name_suffix}"
            rename_map[node.key] = (node.app_label, new_name)
    return rename_map


def _compute_file_replacements(
    node: MigrationNode,
    rename_map: dict[tuple[str, str], tuple[str, str]],
) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for dep in node.dependencies + node.run_before + node.replaces:
        if dep in rename_map:
            result[dep] = rename_map[dep]
    return result


def build_renumber_plan(
    nodes: dict[tuple[str, str], MigrationNode],
    app: str,
    migrations_dir: Path,
) -> MigrationPlan:
    rename_map = _build_rename_map_for_renumber(nodes, app)
    if not rename_map:
        return MigrationPlan(description=f"Renumber {app} (no changes needed)")

    renames: list[FileRename] = []

    # Files being renamed
    for old_key, new_key in rename_map.items():
        node = nodes[old_key]
        file_replacements = _compute_file_replacements(node, rename_map)
        new_content = rewrite_dependencies(node.path, file_replacements)
        new_name = new_key[1]
        new_path = migrations_dir / f"{new_name}.py"
        renames.append(FileRename(old_path=node.path, new_path=new_path, new_content=new_content))

    # Files NOT being renamed but referencing renamed migrations
    renamed_old_keys = set(rename_map.keys())
    for key, node in nodes.items():
        if key in renamed_old_keys:
            continue
        file_replacements = _compute_file_replacements(node, rename_map)
        if file_replacements:
            new_content = rewrite_dependencies(node.path, file_replacements)
            renames.append(
                FileRename(old_path=node.path, new_path=node.path, new_content=new_content)
            )

    return MigrationPlan(renames=renames, description=f"Renumber {app} migrations")


def build_fix_conflicts_plan(
    nodes: dict[tuple[str, str], MigrationNode],
    app: str,
    migrations_dir: Path,
) -> MigrationPlan:
    leaves = leaf_nodes(nodes, app)
    if len(leaves) <= 1:
        return MigrationPlan(description=f"fix-conflicts {app} (no conflicts found)")

    sorted_leaves = sorted(leaves, key=lambda n: n.name)
    winner = sorted_leaves[0]
    losers = sorted_leaves[1:]

    # Max number among non-loser app migrations
    loser_keys = {loser_node.key for loser_node in losers}
    max_base = find_highest_number(nodes, app, exclude_keys=loser_keys)

    rename_map: dict[tuple[str, str], tuple[str, str]] = {}
    for i, loser in enumerate(losers):
        new_number = max_base + i + 1
        new_name = f"{new_number:04d}_{loser.name_suffix}"
        rename_map[loser.key] = (loser.app_label, new_name)

    renames: list[FileRename] = []
    prev_key = winner.key

    for loser in losers:
        old_key = loser.key
        new_key = rename_map[old_key]
        new_name = new_key[1]
        new_path = migrations_dir / f"{new_name}.py"

        # Replace shared parents with prev_key (linearize the fork)
        winner_dep_set = set(winner.dependencies)
        loser_dep_set = set(loser.dependencies)
        shared_parents = loser_dep_set & winner_dep_set

        file_replacements: dict[tuple[str, str], tuple[str, str]] = {}
        for sp in shared_parents:
            file_replacements[sp] = prev_key
        for dep in loser.dependencies:
            if dep in rename_map and dep not in shared_parents:
                file_replacements[dep] = rename_map[dep]

        new_content = rewrite_dependencies(loser.path, file_replacements)
        renames.append(FileRename(old_path=loser.path, new_path=new_path, new_content=new_content))
        prev_key = (loser.app_label, new_name)

    # Update external files referencing the renamed losers
    for key, node in nodes.items():
        if key in loser_keys:
            continue
        file_replacements = _compute_file_replacements(node, rename_map)
        if file_replacements:
            new_content = rewrite_dependencies(node.path, file_replacements)
            renames.append(
                FileRename(old_path=node.path, new_path=node.path, new_content=new_content)
            )

    return MigrationPlan(renames=renames, description=f"Fix conflicts in {app}")


def build_rebase_plan(
    nodes: dict[tuple[str, str], MigrationNode],
    app: str,
    migrations_dir: Path,
    local_names: set[str],
    base_leaf_key: tuple[str, str] | None,
) -> MigrationPlan:
    """Renumber branch-local migrations to follow the base branch's leaf."""
    local_keys = {k for k in nodes if k[0] == app and k[1] in local_names}
    if not local_keys:
        return MigrationPlan(description=f"rebase {app} (no local migrations found)")

    base_nodes = {k: v for k, v in nodes.items() if k[0] == app and k not in local_keys}
    max_base = find_highest_number(base_nodes, app) if base_nodes else 0

    local_sorted = topological_sort({k: v for k, v in nodes.items() if k in local_keys}, app)
    if not local_sorted:
        local_sorted = sorted([nodes[k] for k in local_keys], key=lambda n: n.key)

    rename_map: dict[tuple[str, str], tuple[str, str]] = {}
    for i, node in enumerate(local_sorted):
        new_number = max_base + i + 1
        new_name = f"{new_number:04d}_{node.name_suffix}"
        rename_map[node.key] = (node.app_label, new_name)

    renames: list[FileRename] = []

    for i, node in enumerate(local_sorted):
        old_key = node.key
        new_key = rename_map[old_key]
        new_name = new_key[1]
        new_path = migrations_dir / f"{new_name}.py"

        file_replacements: dict[tuple[str, str], tuple[str, str]] = {}

        # Re-parent first local migration onto base leaf
        if i == 0 and base_leaf_key is not None:
            # Find what the first local migration currently depends on (the old base)
            for dep in node.dependencies:
                if dep[0] == app and dep not in local_keys:
                    file_replacements[dep] = base_leaf_key

        # Replace renamed local deps
        for dep in node.dependencies:
            if dep in rename_map:
                file_replacements[dep] = rename_map[dep]

        new_content = rewrite_dependencies(node.path, file_replacements)
        renames.append(FileRename(old_path=node.path, new_path=new_path, new_content=new_content))

    # Update external files referencing the renamed local migrations
    for key, node in nodes.items():
        if key in local_keys:
            continue
        file_replacements = _compute_file_replacements(node, rename_map)
        if file_replacements:
            new_content = rewrite_dependencies(node.path, file_replacements)
            renames.append(
                FileRename(old_path=node.path, new_path=node.path, new_content=new_content)
            )

    return MigrationPlan(renames=renames, description=f"Rebase {app} migrations")


def validate_graph_improved(
    nodes_before: dict[tuple[str, str], MigrationNode],
    nodes_after: dict[tuple[str, str], MigrationNode],
    app: str,
) -> list[str]:
    """Return list of error messages if the graph got worse after apply."""
    errors: list[str] = []

    # Check: no new cycles
    cycles_before = detect_cycles(nodes_before)
    cycles_after = detect_cycles(nodes_after)
    if len(cycles_after) > len(cycles_before):
        errors.append(f"Apply introduced {len(cycles_after) - len(cycles_before)} new cycle(s)")

    # Check: no new dangling deps
    dangling_before = dangling_dependencies(nodes_before)
    dangling_after = dangling_dependencies(nodes_after)
    if len(dangling_after) > len(dangling_before):
        n = len(dangling_after) - len(dangling_before)
        errors.append(f"Apply introduced {n} new dangling dependency(ies)")

    # Check: app should have exactly 1 leaf after fix-conflicts / renumber
    leaves_after = leaf_nodes(nodes_after, app)
    leaves_before = leaf_nodes(nodes_before, app)
    if len(leaves_after) > 1 and len(leaves_before) == 1:
        errors.append(f"Apply introduced conflicts: {len(leaves_after)} leaf nodes now in {app}")

    return errors
