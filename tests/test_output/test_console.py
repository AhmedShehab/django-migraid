"""Tests for ConsoleOutput."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from migraid.analysis.issues import Issue, Severity
from migraid.output.console import ConsoleOutput


def _console_with_buffer() -> tuple[ConsoleOutput, StringIO]:
    buf = StringIO()
    console = Console(file=buf, highlight=False, width=200)
    return ConsoleOutput(console=console), buf


def _make_issue(
    code: str = "E001",
    severity: Severity = Severity.ERROR,
    app: str = "myapp",
    migration: str | None = "0001_initial",
    message: str = "Test issue",
    fixable: bool = False,
    fix_command: str | None = None,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        app=app,
        migration=migration,
        message=message,
        fixable=fixable,
        fix_command=fix_command,
    )


# ---------------------------------------------------------------------------
# print_issues
# ---------------------------------------------------------------------------


def test_print_issues_empty_list() -> None:
    output, buf = _console_with_buffer()
    output.print_issues([])
    assert "No issues" in buf.getvalue()


def test_print_issues_with_error() -> None:
    output, buf = _console_with_buffer()
    issue = _make_issue(code="E001", severity=Severity.ERROR, message="Conflicting leaves")
    output.print_issues([issue])
    text = buf.getvalue()
    assert "E001" in text
    assert "Conflicting leaves" in text


def test_print_issues_warn_and_info() -> None:
    output, buf = _console_with_buffer()
    issues = [
        _make_issue("W002", Severity.WARN, message="No reverse"),
        _make_issue("I001", Severity.INFO, message="Cross-app risk"),
    ]
    output.print_issues(issues)
    text = buf.getvalue()
    assert "W002" in text
    assert "I001" in text


def test_print_issues_shows_fixable_hint() -> None:
    output, buf = _console_with_buffer()
    issue = _make_issue(
        code="E001",
        fixable=True,
        fix_command="fix-conflicts",
    )
    output.print_issues([issue])
    text = buf.getvalue()
    assert "fix-conflicts" in text


def test_print_issues_no_migration() -> None:
    output, buf = _console_with_buffer()
    issue = _make_issue(migration=None)
    output.print_issues([issue])
    assert "E001" in buf.getvalue()


# ---------------------------------------------------------------------------
# print_diff
# ---------------------------------------------------------------------------


def test_print_diff_shows_changes() -> None:
    output, buf = _console_with_buffer()
    old = 'dependencies = [("myapp", "0001_initial")]\n'
    new = 'dependencies = [("myapp", "0002_step")]\n'
    output.print_diff(old, new, "0002_migration.py")
    text = buf.getvalue()
    assert "0001_initial" in text or "0002_step" in text


def test_print_diff_no_output_when_identical() -> None:
    output, buf = _console_with_buffer()
    output.print_diff("same\n", "same\n", "file.py")
    # No diff output for identical content
    assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# print_plan_summary
# ---------------------------------------------------------------------------


def test_print_plan_summary() -> None:
    output, buf = _console_with_buffer()
    output.print_plan_summary("Renumber myapp", 3)
    text = buf.getvalue()
    assert "Renumber myapp" in text
    assert "3" in text


# ---------------------------------------------------------------------------
# success / error / info / warn
# ---------------------------------------------------------------------------


def test_success_message() -> None:
    output, buf = _console_with_buffer()
    output.success("All done")
    assert "All done" in buf.getvalue()


def test_info_message() -> None:
    output, buf = _console_with_buffer()
    output.info("Just so you know")
    assert "Just so you know" in buf.getvalue()


def test_warn_message() -> None:
    output, buf = _console_with_buffer()
    output.warn("Watch out")
    assert "Watch out" in buf.getvalue()


def test_error_message() -> None:
    output, buf = _console_with_buffer()
    output.error("Something failed")
    # error writes to stderr; the console still buffers it if we don't separate
    # Just ensure it doesn't raise
    # (error calls self._console.print with file=sys.stderr — it bypasses our buffer)


# ---------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------


def test_confirm_yes_flag_skips_input() -> None:
    output, buf = _console_with_buffer()
    output._yes = True
    result = output.confirm("Proceed?")
    assert result is True


def test_confirm_eof_returns_false() -> None:
    """EOFError from input() returns False."""
    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=False)
    output = ConsoleOutput(console=console)
    # In a non-interactive test environment, input() raises EOFError
    result = output.confirm("Proceed?")
    assert result is False
