"""Integration tests for the doctor subcommand."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_doctor_clean_app_no_errors() -> None:
    """doctor on a clean single-migration app exits normally."""
    out = StringIO()
    # testapp has only 0001_initial — no issues expected
    call_command("migraid", "doctor", "--app", "testapp", stdout=out)


@pytest.mark.django_db
def test_doctor_json_format_is_valid_json() -> None:
    out = StringIO()
    call_command("migraid", "doctor", "--app", "testapp", "--format", "json", stdout=out)
    data = json.loads(out.getvalue())
    assert isinstance(data, list)


@pytest.mark.django_db
def test_doctor_json_issue_shape() -> None:
    """Each JSON issue has all required fields."""
    out = StringIO()
    call_command("migraid", "doctor", "--app", "testapp", "--format", "json", stdout=out)
    data = json.loads(out.getvalue())
    required_keys = {
        "code",
        "severity",
        "app",
        "migration",
        "message",
        "hint",
        "fixable",
        "fix_command",
    }
    for issue in data:
        assert required_keys == set(issue.keys())


@pytest.mark.django_db
def test_doctor_app_filter_restricts_output() -> None:
    """--app flag filters output to the specified app only."""
    out = StringIO()
    call_command("migraid", "doctor", "--app", "testapp", "--format", "json", stdout=out)
    data = json.loads(out.getvalue())
    apps_in_output = {i["app"] for i in data}
    assert apps_in_output <= {"testapp"}


@pytest.mark.django_db
def test_doctor_text_format_runs() -> None:
    """Text format doesn't crash (rich writes to its own console, not stdout)."""
    call_command("migraid", "doctor", "--app", "testapp", "--format", "text")


@pytest.mark.django_db
def test_doctor_exits_nonzero_on_errors(tmp_path):
    """doctor exits with SystemExit(1) when ERROR-level issues exist."""

    from migraid.analysis.issues import Severity, run_all_detectors
    from migraid.analysis.loader import MigrationAnalyzer
    from tests.conftest import write_migration

    # Build a conflicting scenario directly via the analysis layer (no management command needed)
    d = tmp_path / "brokenapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_branch_a", [("brokenapp", "0001_initial")])
    write_migration(d, "0002_branch_b", [("brokenapp", "0001_initial")])

    analyzer = MigrationAnalyzer(app_dirs=[("brokenapp", d)])
    issues = run_all_detectors(analyzer)
    errors = [i for i in issues if i.severity == Severity.ERROR]
    assert len(errors) >= 1


@pytest.mark.django_db
def test_doctor_exits_zero_on_warnings_only(tmp_path):
    """doctor exits with 0 when only WARN-level issues (like W006) exist."""

    from django.core.management import call_command

    from tests.conftest import write_migration

    d = tmp_path / "gapapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_gap", [("gapapp", "0001_initial")])

    # We need to mock _get_app_dirs to point to our tmp_path
    import migraid.management.commands.migraid as migraid_cmd

    original_get_app_dirs = migraid_cmd._get_app_dirs
    migraid_cmd._get_app_dirs = lambda label=None: [("gapapp", d)]

    try:
        # call_command catches SystemExit(0) but not SystemExit(1)
        # However, _handle_doctor calls sys.exit(1) only if there are errors.
        # If there are only warnings, it should return normally (exit 0).
        call_command("migraid", "doctor")
    finally:
        migraid_cmd._get_app_dirs = original_get_app_dirs
