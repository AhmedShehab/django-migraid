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
    LinearizeError,
    MigrationPlan,
    PlanExecutor,
    UndoEntry,
    build_fix_conflicts_plan,
    build_linearize_plan,
    build_rebase_plan,
    build_renumber_plan,
    validate_graph_improved,
)
from ...operations.sync_branch import build_sync_branch_plan
from ...operations.table_sync import (
    TableSyncCollisionError,
    TableSyncError,
    TableSyncPlan,
    build_table_sync_plan,
    describe_connection,
    render_sql,
    write_undo_file,
)
from ...operations.table_sync import execute as execute_table_sync
from ...output.console import ConsoleOutput


class _PostApplyError(Exception):
    """Internal signal that post-apply validation found regressions."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("post-apply validation failed")
        self.errors = errors


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


def _add_db_sync_args(parser: CommandParser) -> None:
    """Shared --update-db / --noinput / --database flags for the rewrite commands."""
    parser.add_argument(
        "--update-db",
        action="store_true",
        dest="update_db",
        help=(
            "Also rename matching django_migrations rows for applied migrations "
            "(preserves the applied timestamp). Implies --allow-applied."
        ),
    )
    # Deprecated alias — hidden so it doesn't appear in --help
    parser.add_argument(
        "--sync-db",
        action="store_true",
        dest="update_db",
        help="Deprecated: use --update-db.",
        default=False,
    )
    parser.add_argument(
        "--noinput",
        "--no-input",
        action="store_true",
        dest="no_input",
        help="Run non-interactively (CI): skip the confirmation prompt. Alias for --yes.",
    )
    parser.add_argument(
        "--database",
        default="default",
        metavar="ALIAS",
        help="Database alias whose django_migrations table to update (default: default).",
    )


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
    *,
    update_db: bool = False,
    db_alias: str = "default",
) -> None:
    if plan.is_empty():
        output.success(f"{plan.description}: nothing to do.")
        return

    output.print_plan_summary(plan.description, len(plan.renames))
    executor.preview(plan)

    # Build the django_migrations update plan up front so collisions abort before
    # any file is touched, and so the preview shows exactly what the DB update does.
    sync_plan = None
    if update_db:
        from django.db import connections

        connection = connections[db_alias]
        try:
            sync_plan = build_table_sync_plan(
                plan.key_renames,
                analyzer.applied_migrations(),
                deleted_keys=set(plan.deleted_keys),
            )
        except TableSyncCollisionError as exc:
            raise CommandError(str(exc)) from exc
        if sync_plan.is_empty():
            output.info("No applied django_migrations rows need updating.")
        else:
            output.print_table_sync(
                describe_connection(connection),
                sync_plan.mappings,
                render_sql(sync_plan.mappings, sync_plan.deletions),
                skipped=len(sync_plan.skipped),
                deleted=len(sync_plan.deletions),
            )

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

    if sync_plan is not None and not sync_plan.is_empty():
        _apply_with_db_sync(
            plan, sync_plan, analyzer, app, output, executor, db_alias, backup_branch
        )
    else:
        _apply_files_only(plan, analyzer, app, output, executor, backup_branch)

    output.success(plan.description)


def _apply_files_only(
    plan: MigrationPlan,
    analyzer: MigrationAnalyzer,
    app: str,
    output: ConsoleOutput,
    executor: PlanExecutor,
    backup_branch: str | None,
) -> None:
    nodes_before = dict(analyzer.nodes)
    executor.apply(plan)

    analyzer.reload()
    errors = validate_graph_improved(nodes_before, analyzer.nodes, app)
    if errors:
        output.error("Post-apply validation failed — reverting changes:")
        for err in errors:
            output.error(f"  {err}")
        raise CommandError(
            "Post-apply validation detected regressions. "
            f"Backup branch '{backup_branch}' remains for manual recovery."
        )


def _apply_with_db_sync(
    plan: MigrationPlan,
    sync_plan: TableSyncPlan,
    analyzer: MigrationAnalyzer,
    app: str,
    output: ConsoleOutput,
    executor: PlanExecutor,
    db_alias: str,
    backup_branch: str | None,
) -> None:
    """Apply files and django_migrations row renames as one atomic, reversible unit."""
    from pathlib import Path as _Path

    from django.db import connections, transaction

    connection = connections[db_alias]
    nodes_before = dict(analyzer.nodes)
    undo_log: list[UndoEntry] = []
    undo_file = None

    try:
        with transaction.atomic(using=db_alias):
            undo_log = executor.apply(plan)
            # Write the inverse-SQL undo script before the UPDATEs commit, so a
            # crash mid-commit still leaves a recovery path on disk.
            undo_file = write_undo_file(
                sync_plan.mappings, deletions=sync_plan.deletions, label=app
            )
            execute_table_sync(connection, sync_plan.mappings, sync_plan.deletions)

            analyzer.reload()
            errors = validate_graph_improved(nodes_before, analyzer.nodes, app)
            if errors:
                raise _PostApplyError(errors)
    except Exception as exc:
        executor.undo(undo_log)  # DB rolled back by atomic; replay the file undo
        if undo_file is not None:
            _Path(undo_file).unlink(missing_ok=True)
        analyzer.reload()
        if isinstance(exc, _PostApplyError):
            output.error("Post-apply validation failed — reverted files and DB:")
            for err in exc.errors:
                output.error(f"  {err}")
            raise CommandError(
                "Post-apply validation detected regressions; all changes reverted. "
                f"Backup branch '{backup_branch}' remains."
            ) from exc
        if isinstance(exc, (TableSyncError, TableSyncCollisionError)):
            raise CommandError(
                f"django_migrations sync failed; all changes reverted: {exc}"
            ) from exc
        raise

    output.info(f"Wrote DB undo script: {undo_file}")
    touched = len(sync_plan.mappings) + len(sync_plan.deletions)
    output.success(f"Synced {touched} django_migrations row(s).")


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
        _add_db_sync_args(rebase)

        # fix-conflicts
        fc = subparsers.add_parser("fix-conflicts", help="Linearize conflicting leaf migrations")
        fc.add_argument("--app", metavar="LABEL", help="Limit to one app")
        fc.add_argument("--dry-run", action="store_true")
        fc.add_argument("--yes", action="store_true")
        fc.add_argument("--force", action="store_true")
        fc.add_argument("--allow-applied", action="store_true")
        _add_db_sync_args(fc)

        # linearize
        lin = subparsers.add_parser(
            "linearize",
            help="Rewrite history to a gap-free 0001..N chain with one parent each",
        )
        lin.add_argument("--app", metavar="LABEL", help="Limit to one app")
        lin.add_argument(
            "--strip-cross-app",
            action="store_true",
            help="Also drop cross-app dependencies (dangerous — can break migrate order)",
        )
        lin.add_argument("--dry-run", action="store_true")
        lin.add_argument("--yes", action="store_true", help="Skip confirmation")
        lin.add_argument("--force", action="store_true", help="Skip dirty-tree check")
        lin.add_argument("--allow-applied", action="store_true")
        _add_db_sync_args(lin)

        # renumber
        rn = subparsers.add_parser("renumber", help="Fix gap/duplicate numbering for an app")
        rn.add_argument("app", help="App label to renumber")
        rn.add_argument("--dry-run", action="store_true")
        rn.add_argument("--yes", action="store_true")
        rn.add_argument("--force", action="store_true")
        rn.add_argument("--allow-applied", action="store_true")
        _add_db_sync_args(rn)

        # prune
        prune = subparsers.add_parser("prune", help="Remove stale django_migrations rows")
        prune.add_argument("--dry-run", action="store_true", help="Preview only, no rows deleted")
        prune.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
        prune.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            dest="no_input",
            help="Alias for --yes (non-interactive / CI).",
        )
        prune.add_argument(
            "--database",
            default="default",
            metavar="ALIAS",
            help="Database alias to prune (default: default).",
        )
        prune.add_argument(
            "--allow-remote-db",
            action="store_true",
            dest="allow_remote_db",
            help="Allow pruning against a non-local database host.",
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

        # sync-branch
        sb = subparsers.add_parser(
            "sync-branch",
            help="Align migration files (and optionally the DB) to the current git branch state",
        )
        sb.add_argument("--app", metavar="LABEL", help="Limit to one app")
        sb.add_argument("--dry-run", action="store_true", help="Preview only, no changes made")
        sb.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
        sb.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            dest="no_input",
            help="Alias for --yes (non-interactive / CI).",
        )
        sb.add_argument(
            "--database",
            default="default",
            metavar="ALIAS",
            help="Database alias to inspect (default: default).",
        )
        sb.add_argument(
            "--update-db",
            action="store_true",
            dest="update_db",
            help="Also delete stale django_migrations rows for branch-excess applied migrations.",
        )
        sb.add_argument(
            "--schema",
            action="store_true",
            help=(
                "Also run reverse Django migrations (database_backwards) for excess applied "
                "migrations. Requires the migration files to still be present on disk."
            ),
        )

    def handle(self, *_args: Any, **options: Any) -> None:  # noqa: ANN401
        if "--sync-db" in sys.argv:
            sys.stderr.write(
                "Warning: --sync-db is deprecated and will be removed in a future release. "
                "Use --update-db instead.\n"
            )
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
        yes: bool = options.get("yes", False) or options.get("no_input", False)
        force: bool = options.get("force", False)
        update_db: bool = options.get("update_db", False)
        db_alias: str = options.get("database", "default")
        # --update-db renames rows in step with files, so applied renames are safe.
        allow_applied: bool = options.get("allow_applied", False) or update_db

        from django.db import connections

        connection = connections[db_alias]

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
        _execute_plan(
            plan, analyzer, app, output, executor, guard, update_db=update_db, db_alias=db_alias
        )

    # ------------------------------------------------------------------
    # fix-conflicts
    # ------------------------------------------------------------------

    def _handle_fix_conflicts(self, options: dict[str, Any]) -> None:
        app_label: str | None = options.get("app")
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False) or options.get("no_input", False)
        force: bool = options.get("force", False)
        update_db: bool = options.get("update_db", False)
        db_alias: str = options.get("database", "default")
        allow_applied: bool = options.get("allow_applied", False) or update_db

        from django.db import connections

        connection = connections[db_alias]

        app_dirs = _get_app_dirs(app_label)
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)

        from ...analysis.graph import leaf_nodes

        apps_with_conflicts = [
            a for a in {k[0] for k in analyzer.nodes} if len(leaf_nodes(analyzer.nodes, a)) > 1
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
            _execute_plan(
                plan, analyzer, app, output, executor, guard, update_db=update_db, db_alias=db_alias
            )

    # ------------------------------------------------------------------
    # linearize
    # ------------------------------------------------------------------

    def _handle_linearize(self, options: dict[str, Any]) -> None:
        app_label: str | None = options.get("app")
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False) or options.get("no_input", False)
        force: bool = options.get("force", False)
        strip_cross_app: bool = options.get("strip_cross_app", False)
        update_db: bool = options.get("update_db", False)
        db_alias: str = options.get("database", "default")
        allow_applied: bool = options.get("allow_applied", False) or update_db

        from django.db import connections

        connection = connections[db_alias]

        app_dirs = _get_app_dirs(app_label)
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)
        output = ConsoleOutput(yes=yes)

        apps_to_do = sorted({k[0] for k in analyzer.nodes})
        if app_label:
            apps_to_do = [a for a in apps_to_do if a == app_label]
        if not apps_to_do:
            output.success("No migrations found to linearize.")
            return

        guard = None if dry_run else _build_guard(force)

        for app in apps_to_do:
            _safety_check_applied(analyzer, app, allow_applied)
            migrations_dir = _get_migrations_dir(app)
            try:
                plan = build_linearize_plan(
                    analyzer.nodes, app, migrations_dir, strip_cross_app=strip_cross_app
                )
            except LinearizeError as exc:
                raise CommandError(str(exc)) from exc
            executor = PlanExecutor(dry_run=dry_run, output=output)
            _execute_plan(
                plan, analyzer, app, output, executor, guard, update_db=update_db, db_alias=db_alias
            )

    # ------------------------------------------------------------------
    # rebase
    # ------------------------------------------------------------------

    def _handle_rebase(self, options: dict[str, Any]) -> None:
        base_branch: str = options.get("base", "main")
        app_label: str | None = options.get("app")
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False) or options.get("no_input", False)
        force: bool = options.get("force", False)
        update_db: bool = options.get("update_db", False)
        db_alias: str = options.get("database", "default")
        allow_applied: bool = options.get("allow_applied", False) or update_db

        from django.db import connections

        connection = connections[db_alias]

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
            _execute_plan(
                plan, analyzer, app, output, executor, guard, update_db=update_db, db_alias=db_alias
            )

    # ------------------------------------------------------------------
    # prune
    # ------------------------------------------------------------------

    def _handle_prune(self, options: dict[str, Any]) -> None:
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False) or options.get("no_input", False)
        allow_remote_db: bool = options.get("allow_remote_db", False)
        db_alias: str = options.get("database", "default")

        from django.db import connections

        connection = connections[db_alias]

        # Safety: refuse non-local DB unless --allow-remote-db
        if not allow_remote_db and not dry_run:
            db_settings = connection.settings_dict
            engine = db_settings.get("ENGINE", "")
            host = db_settings.get("HOST", "localhost") or "localhost"
            is_local = "sqlite" in engine or host in ("localhost", "127.0.0.1", "")
            if not is_local:
                raise CommandError(
                    f"Database host '{host}' doesn't look local. "
                    "Use --allow-remote-db to allow pruning on non-local databases."
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

    # ------------------------------------------------------------------
    # sync-branch
    # ------------------------------------------------------------------

    def _handle_sync_branch(self, options: dict[str, Any]) -> None:
        app_label: str | None = options.get("app")
        dry_run: bool = options.get("dry_run", False)
        yes: bool = options.get("yes", False) or options.get("no_input", False)
        db_alias: str = options.get("database", "default")
        update_db: bool = options.get("update_db", False)
        schema: bool = options.get("schema", False)

        from django.db import connections

        connection = connections[db_alias]

        try:
            guard = GitGuard()
        except NotAGitRepoError as exc:
            raise CommandError(f"sync-branch requires a git repository: {exc}") from exc

        app_dirs = _get_app_dirs(app_label)
        analyzer = MigrationAnalyzer(app_dirs=app_dirs, connection=connection)
        applied = analyzer.applied_migrations()

        plan = build_sync_branch_plan(guard, app_dirs, applied, update_db=update_db, schema=schema)
        output = ConsoleOutput(yes=yes)

        # Surface a hint when stale rows exist but --update-db was not given
        if plan.unauthorized_stale:
            output.info(
                f"{plan.unauthorized_stale} stale django_migrations row(s) found "
                "— re-run with --update-db to remove them."
            )

        if plan.is_empty():
            output.success("sync-branch: nothing to do.")
            return

        if plan.schema_targets:
            output.info(
                f"--schema: will run migrate backwards for {len(plan.schema_targets)} app(s):"
            )
            for app, target in sorted(plan.schema_targets.items()):
                output.info(f"  {app} → {target or 'zero'}")

        if plan.stale_rows:
            self.stdout.write(f"Stale django_migrations rows to delete: {len(plan.stale_rows)}")
            for app, name in plan.stale_rows:
                self.stdout.write(f"  {app}.{name}")

        if plan.untracked_files:
            self.stdout.write(f"Untracked migration files to delete: {len(plan.untracked_files)}")
            for f in plan.untracked_files:
                self.stdout.write(f"  {f}")

        if dry_run:
            output.info("Dry run — no changes made.")
            return

        if not output.confirm("Apply these changes?"):
            output.info("Aborted.")
            return

        if plan.schema_targets:
            from django.core.management import call_command as _call_migrate

            for app, target in sorted(plan.schema_targets.items()):
                target_arg = target or "zero"
                output.info(f"Migrating {app} to {target_arg}...")
                try:
                    _call_migrate("migrate", app, target_arg, database=db_alias, verbosity=1)
                except Exception as exc:
                    raise CommandError(f"Failed to migrate {app} to {target_arg}: {exc}") from exc
                output.success(f"Migrated {app} to {target_arg}.")

        if plan.stale_rows:
            from django.db.migrations.recorder import MigrationRecorder

            recorder = MigrationRecorder(connection)
            for app, name in plan.stale_rows:
                recorder.record_unapplied(app, name)
            output.success(f"Deleted {len(plan.stale_rows)} stale django_migrations row(s).")

        if plan.untracked_files:
            for f in plan.untracked_files:
                f.unlink()
            output.success(f"Deleted {len(plan.untracked_files)} untracked migration file(s).")
