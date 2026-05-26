"""django-migraid management command with subcommands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...analysis.issues import Severity, run_all_detectors
from ...analysis.loader import MigrationAnalyzer
from ...operations.backup import DirtyWorkingTreeError, GitGuard, NotAGitRepoError
from ...operations.plan import (
    MigrationPlan,
    PlanExecutor,
    build_fix_conflicts_plan,
    build_rebase_plan,
    build_renumber_plan,
    validate_graph_improved,
)
from ...output.console import ConsoleOutput


def _get_app_dirs(app_label: str | None = None) -> list[tuple[str, Path]]:
    from django.apps import apps

    result: list[tuple[str, Path]] = []
    for app_config in apps.get_app_configs():
        if app_label and app_config.label != app_label:
            continue
        migrations_dir = Path(app_config.path) / "migrations"
        if migrations_dir.is_dir():
            result.append((app_config.label, migrations_dir))
    return result


def _get_migrations_dir(app_label: str) -> Path:
    from django.apps import apps

    try:
        app_config = apps.get_app_config(app_label)
    except LookupError as exc:
        raise CommandError(f"App '{app_label}' is not in INSTALLED_APPS") from exc
    return Path(app_config.path) / "migrations"


def _build_guard(force: bool) -> GitGuard | None:
    try:
        guard = GitGuard()
        guard.assert_clean_working_tree(force=force)
        return guard
    except NotAGitRepoError:
        if not force:
            raise CommandError(
                "Not in a git repository. Use --force to run without git safety checks."
            ) from None
        return None
    except DirtyWorkingTreeError as exc:
        raise CommandError(str(exc)) from exc


def _safety_check_applied(
    analyzer: MigrationAnalyzer,
    app: str,
    allow_applied: bool,
) -> None:
    if allow_applied:
        return
    applied = analyzer.applied_migrations()
    if not applied:
        return
    app_nodes = {k for k in analyzer.nodes if k[0] == app}
    blocked = [k for k in app_nodes if k in applied]
    if blocked:
        raise CommandError(
            f"App '{app}' has {len(blocked)} applied migration(s). "
            "Renaming applied migrations desyncs the database. "
            "Use --allow-applied to override (use with caution)."
        )


def _execute_plan(
    plan: MigrationPlan,
    analyzer: MigrationAnalyzer,
    app: str,
    output: ConsoleOutput,
    executor: PlanExecutor,
    guard: GitGuard | None,
) -> None:
    if plan.is_empty():
        output.success(f"{plan.description}: nothing to do.")
        return

    output.print_plan_summary(plan.description, len(plan.renames))
    executor.preview(plan)

    if executor.dry_run:
        return

    if not output.confirm("Apply these changes?"):
        output.info("Aborted.")
        return

    backup_branch: str | None = None
    if guard is not None:
        try:
            backup_branch = guard.create_backup_branch()
            output.info(f"Created backup ref: {backup_branch}")
        except Exception as exc:
            output.warn(f"Could not create backup branch: {exc}")

    nodes_before = dict(analyzer.nodes)
    executor.apply(plan)

    # Post-apply self-validation
    analyzer.reload()
    nodes_after = analyzer.nodes
    errors = validate_graph_improved(nodes_before, nodes_after, app)
    if errors:
        output.error("Post-apply validation failed — reverting changes:")
        for err in errors:
            output.error(f"  {err}")
        # Revert via undo log would already have run if apply threw; reload reflects current state
        raise CommandError(
            "Post-apply validation detected regressions. "
            f"Backup branch '{backup_branch}' remains for manual recovery."
        )

    output.success(plan.description)


class Command(BaseCommand):
    help = "Detect, diagnose, and auto-fix Django migration problems in Git workflows."

    def add_arguments(self, parser: CommandParser) -> None:
        subparsers = parser.add_subparsers(dest="subcommand", metavar="subcommand")
        subparsers.required = True

        # doctor
        doctor = subparsers.add_parser("doctor", help="Scan for migration issues (read-only)")
        doctor.add_argument("--app", metavar="LABEL", help="Limit to one app")
        doctor.add_argument(
            "--format", choices=["text", "json"], default="text", help="Output format"
        )

        # rebase
        rebase = subparsers.add_parser(
            "rebase", help="Renumber branch-local migrations onto a target branch"
        )
        rebase.add_argument("--base", default="main", metavar="BRANCH", help="Base git branch")
        rebase.add_argument("--app", metavar="LABEL", help="Limit to one app")
        rebase.add_argument("--dry-run", action="store_true")
        rebase.add_argument("--yes", action="store_true", help="Skip confirmation")
        rebase.add_argument("--force", action="store_true", help="Skip dirty-tree check")
        rebase.add_argument(
            "--allow-applied",
            action="store_true",
            help="Allow renaming applied migrations (dangerous)",
        )

        # fix-conflicts
        fc = subparsers.add_parser("fix-conflicts", help="Linearize conflicting leaf migrations")
        fc.add_argument("--app", metavar="LABEL", help="Limit to one app")
        fc.add_argument("--dry-run", action="store_true")
        fc.add_argument("--yes", action="store_true")
        fc.add_argument("--force", action="store_true")
        fc.add_argument("--allow-applied", action="store_true")

        # renumber
        rn = subparsers.add_parser("renumber", help="Fix gap/duplicate numbering for an app")
        rn.add_argument("app", help="App label to renumber")
        rn.add_argument("--dry-run", action="store_true")
        rn.add_argument("--yes", action="store_true")
        rn.add_argument("--force", action="store_true")
        rn.add_argument("--allow-applied", action="store_true")

        # prune
        prune = subparsers.add_parser(
            "prune", help="Remove stale django_migrations rows (dry-run by default)"
        )
        prune.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Preview only (default — use --yes to execute)",
        )
        prune.add_argument("--yes", action="store_true", help="Actually delete rows")
        prune.add_argument(
            "--allow-applied",
            action="store_true",
            help="Allow running against non-local databases",
        )

        # graph
        graph = subparsers.add_parser("graph", help="Visualize the migration DAG")
        graph.add_argument("app", nargs="?", metavar="LABEL", help="Limit to one app")
        graph.add_argument(
            "--format",
            choices=["ascii", "mermaid", "dot"],
            default="ascii",
        )
        graph.add_argument("--output", metavar="FILE", help="Write to file instead of stdout")

    def handle(self, *_args: Any, **options: Any) -> None:  # noqa: ANN401
        subcommand: str = options["subcommand"]
        handler = getattr(self, f"_handle_{subcommand.replace('-', '_')}")
        handler(options)

    # ------------------------------------------------------------------
    # doctor
    # ------------------------------------------------------------------

    def _handle_doctor(self, options: dict[str, Any]) -> None:
        app_label: str | None = options.get("app")
        fmt: str = options.get("format", "text")

        from django.db import connection

        app_dirs = _get_app_dirs(app_label)
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)
        issues = run_all_detectors(analyzer, app=app_label)

        if fmt == "json":
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "code": i.code,
                            "severity": i.severity.value,
                            "app": i.app,
                            "migration": i.migration,
                            "message": i.message,
                            "hint": i.hint,
                            "fixable": i.fixable,
                            "fix_command": i.fix_command,
                        }
                        for i in issues
                    ],
                    indent=2,
                )
            )
        else:
            output = ConsoleOutput()
            output.print_issues(issues)

        errors = [i for i in issues if i.severity == Severity.ERROR]
        if errors:
            sys.exit(1)

    # ------------------------------------------------------------------
    # renumber
    # ------------------------------------------------------------------

    def _handle_renumber(self, options: dict[str, Any]) -> None:
        app: str = options["app"]
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False)
        force: bool = options.get("force", False)
        allow_applied: bool = options.get("allow_applied", False)

        from django.db import connection

        migrations_dir = _get_migrations_dir(app)
        if not migrations_dir.is_dir():
            raise CommandError(f"No migrations directory for app '{app}'")

        app_dirs = _get_app_dirs()
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)
        _safety_check_applied(analyzer, app, allow_applied)

        guard = None if dry_run else _build_guard(force)
        plan = build_renumber_plan(analyzer.nodes, app, migrations_dir)
        output = ConsoleOutput(yes=yes)
        executor = PlanExecutor(dry_run=dry_run, output=output)
        _execute_plan(plan, analyzer, app, output, executor, guard)

    # ------------------------------------------------------------------
    # fix-conflicts
    # ------------------------------------------------------------------

    def _handle_fix_conflicts(self, options: dict[str, Any]) -> None:
        app_label: str | None = options.get("app")
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False)
        force: bool = options.get("force", False)
        allow_applied: bool = options.get("allow_applied", False)

        from django.db import connection

        app_dirs = _get_app_dirs(app_label)
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)

        from ...analysis.graph import leaf_nodes

        apps_with_conflicts = [
            a
            for a in {k[0] for k in analyzer.nodes}
            if len(leaf_nodes(analyzer.nodes, a)) > 1
        ]
        if app_label:
            apps_with_conflicts = [a for a in apps_with_conflicts if a == app_label]

        if not apps_with_conflicts:
            ConsoleOutput().success("No conflicting migrations found.")
            return

        output = ConsoleOutput(yes=yes)
        guard = None if dry_run else _build_guard(force)

        for app in apps_with_conflicts:
            _safety_check_applied(analyzer, app, allow_applied)
            migrations_dir = _get_migrations_dir(app)
            plan = build_fix_conflicts_plan(analyzer.nodes, app, migrations_dir)
            executor = PlanExecutor(dry_run=dry_run, output=output)
            _execute_plan(plan, analyzer, app, output, executor, guard)

    # ------------------------------------------------------------------
    # rebase
    # ------------------------------------------------------------------

    def _handle_rebase(self, options: dict[str, Any]) -> None:
        base_branch: str = options.get("base", "main")
        app_label: str | None = options.get("app")
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False)
        force: bool = options.get("force", False)
        allow_applied: bool = options.get("allow_applied", False)

        from django.db import connection

        app_dirs = _get_app_dirs(app_label)
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)
        output = ConsoleOutput(yes=yes)

        try:
            guard = GitGuard()
            guard.assert_clean_working_tree(force=force)
        except NotAGitRepoError:
            if not force:
                raise CommandError(
                    "Not in a git repository. Use --force to skip git checks."
                ) from None
            guard = None
        except DirtyWorkingTreeError as exc:
            raise CommandError(str(exc)) from exc

        apps_to_rebase = sorted({k[0] for k in analyzer.nodes})
        if app_label:
            apps_to_rebase = [a for a in apps_to_rebase if a == app_label]

        for app in apps_to_rebase:
            local_names: set[str] = set()
            base_leaf_key: tuple[str, str] | None = None

            if guard is not None:
                local_names = guard.local_migrations_since(base_branch, app)
                if not local_names:
                    continue
                # Determine base leaf
                base_leaf_name = guard.base_leaf_for_app(base_branch, app)
                if base_leaf_name:
                    base_leaf_key = (app, base_leaf_name)
            else:
                output.warn(f"No git context — skipping rebase for {app}")
                continue

            _safety_check_applied(analyzer, app, allow_applied)
            migrations_dir = _get_migrations_dir(app)
            plan = build_rebase_plan(
                analyzer.nodes, app, migrations_dir, local_names, base_leaf_key
            )
            executor = PlanExecutor(dry_run=dry_run, output=output)
            _execute_plan(plan, analyzer, app, output, executor, guard)

    # ------------------------------------------------------------------
    # prune
    # ------------------------------------------------------------------

    def _handle_prune(self, options: dict[str, Any]) -> None:
        yes: bool = options.get("yes", False)
        dry_run: bool = not yes
        allow_applied: bool = options.get("allow_applied", False)

        from django.db import connection

        # Safety: refuse non-local DB unless --allow-applied
        if not allow_applied and not dry_run:
            db_settings = connection.settings_dict
            engine = db_settings.get("ENGINE", "")
            host = db_settings.get("HOST", "localhost") or "localhost"
            is_local = "sqlite" in engine or host in ("localhost", "127.0.0.1", "")
            if not is_local:
                raise CommandError(
                    f"Database host '{host}' doesn't look local. "
                    "Use --allow-applied to allow pruning on non-local databases."
                )

        app_dirs = _get_app_dirs()
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)
        applied = analyzer.applied_migrations()
        disk_keys = set(analyzer.nodes.keys())
        stale = sorted(k for k in applied if k not in disk_keys)

        output = ConsoleOutput(yes=yes)

        if not stale:
            output.success("No stale django_migrations rows found.")
            return

        self.stdout.write(f"Found {len(stale)} stale row(s):")
        for key in stale:
            self.stdout.write(f"  {key[0]}.{key[1]}")

        if dry_run:
            output.info("Dry run — no rows deleted. Use --yes to actually delete.")
            return

        if not output.confirm(f"Delete {len(stale)} stale row(s) from django_migrations?"):
            output.info("Aborted.")
            return

        from django.db.migrations.recorder import MigrationRecorder

        recorder = MigrationRecorder(connection)
        for key in stale:
            recorder.record_unapplied(key[0], key[1])
        output.success(f"Deleted {len(stale)} stale row(s).")

    # ------------------------------------------------------------------
    # graph
    # ------------------------------------------------------------------

    def _handle_graph(self, options: dict[str, Any]) -> None:
        app_label: str | None = options.get("app")
        fmt: str = options.get("format", "ascii")
        output_file: str | None = options.get("output")

        app_dirs = _get_app_dirs(app_label)
        analyzer = MigrationAnalyzer(app_dirs=app_dirs)
        nodes = analyzer.nodes

        apps = sorted({k[0] for k in nodes})
        if app_label:
            apps = [a for a in apps if a == app_label]

        lines: list[str] = []

        if fmt == "mermaid":
            lines.append("graph TD")
            for key, node in sorted(nodes.items()):
                if apps and key[0] not in apps:
                    continue
                node_id = f"{key[0]}_{key[1]}".replace("-", "_")
                label = f"{key[0]}.{key[1]}"
                lines.append(f'    {node_id}["{label}"]')
                for dep in node.dependencies:
                    dep_id = f"{dep[0]}_{dep[1]}".replace("-", "_")
                    lines.append(f"    {dep_id} --> {node_id}")

        elif fmt == "dot":
            lines.append("digraph migrations {")
            lines.append("    rankdir=LR;")
            for key, node in sorted(nodes.items()):
                if apps and key[0] not in apps:
                    continue
                node_id = f'"{key[0]}.{key[1]}"'
                for dep in node.dependencies:
                    dep_id = f'"{dep[0]}.{dep[1]}"'
                    lines.append(f"    {dep_id} -> {node_id};")
            lines.append("}")

        else:  # ascii
            from ...analysis.graph import leaf_nodes as _leaf_nodes

            for app in apps:
                lines.append(f"\n=== {app} ===")
                from ...analysis.graph import topological_sort

                app_nodes = topological_sort(nodes, app)
                leaves = {n.key for n in _leaf_nodes(nodes, app)}
                for node in app_nodes:
                    marker = " [HEAD]" if node.key in leaves else ""
                    dep_str = ", ".join(f"{d[0]}.{d[1]}" for d in node.dependencies)
                    deps_display = f" ← [{dep_str}]" if dep_str else ""
                    lines.append(f"  {node.name}{marker}{deps_display}")

        result = "\n".join(lines)
        if output_file:
            Path(output_file).write_text(result + "\n", encoding="utf-8")
            ConsoleOutput().success(f"Wrote graph to {output_file}")
        else:
            self.stdout.write(result)
