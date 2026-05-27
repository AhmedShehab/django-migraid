"""Rich-based CLI output for django-migraid."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

if TYPE_CHECKING:
    from ..analysis.issues import Issue
    from ..operations.table_sync import RowMapping


class ConsoleOutput:
    def __init__(self, console: Console | None = None, yes: bool = False) -> None:
        self._console = console or Console()
        self._yes = yes

    def print_issues(self, issues: list[Issue]) -> None:
        if not issues:
            self._console.print("[green]✓ No issues found.[/green]")
            return

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold", expand=True)
        table.add_column("Code", style="bold", width=6, no_wrap=True)
        table.add_column("Severity", width=8, no_wrap=True)
        table.add_column("App", width=20, no_wrap=True)
        table.add_column("Migration", width=35)
        table.add_column("Message")

        color_map = {"error": "red", "warn": "yellow", "info": "blue"}
        for issue in issues:
            color = color_map.get(issue.severity.value, "white")
            table.add_row(
                f"[{color}]{issue.code}[/{color}]",
                f"[{color}]{issue.severity.value.upper()}[/{color}]",
                issue.app,
                issue.migration or "—",
                issue.message,
            )

        self._console.print(table)

        fixable = [i for i in issues if i.fixable]
        if fixable:
            self._console.print()
            self._console.print("[dim]Fixable issues:[/dim]")
            for issue in fixable:
                cmd = issue.fix_command or ""
                self._console.print(
                    f"  [dim]{issue.code}[/dim] → [cyan]python manage.py migraid {cmd}[/cyan]"
                )

    def print_diff(self, old: str, new: str, filename: str) -> None:
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
        diff_text = "".join(diff)
        if diff_text:
            syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=False)
            self._console.print(syntax)

    def print_plan_summary(self, description: str, n_changes: int) -> None:
        self._console.print(f"[bold]{description}[/bold]: {n_changes} file(s) to change")

    def print_table_sync(
        self,
        target: str,
        mappings: list[RowMapping],
        sql: list[str],
        skipped: int = 0,
    ) -> None:
        """Show exactly what the django_migrations sync will do before the prompt."""
        self._console.print()
        self._console.print(f"[bold]Target DB:[/bold] {target}")
        self._console.print(f"[bold]django_migrations changes[/bold] ({len(mappings)} row(s)):")

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
        table.add_column("App", no_wrap=True)
        table.add_column("Old name")
        table.add_column("New name")
        table.add_column("Applied (kept)", no_wrap=True)
        for m in mappings:
            applied = "—" if m.applied is None else str(m.applied)
            table.add_row(m.app, m.old_name, f"[cyan]{m.new_name}[/cyan]", applied)
        self._console.print(table)

        if skipped:
            self._console.print(
                f"[dim]{skipped} renamed migration(s) had no recorded row — skipped.[/dim]"
            )

        self._console.print("[bold]SQL to run:[/bold]")
        sql_text = "\n".join(sql)
        self._console.print(Syntax(sql_text, "sql", theme="monokai", line_numbers=False))

    def confirm(self, prompt: str) -> bool:
        if self._yes:
            self._console.print(f"[dim]{prompt} → yes (--yes)[/dim]")
            return True
        try:
            response = input(f"{prompt} [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt, OSError):
            return False
        return response in ("y", "yes")

    def success(self, msg: str) -> None:
        self._console.print(f"[green]✓ {msg}[/green]")

    def error(self, msg: str) -> None:
        self._console.print(f"[red]✗ {msg}[/red]")

    def info(self, msg: str) -> None:
        self._console.print(f"[blue]ℹ {msg}[/blue]")

    def warn(self, msg: str) -> None:
        self._console.print(f"[yellow]⚠ {msg}[/yellow]")
