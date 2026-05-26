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
