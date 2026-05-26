"""Tests for issue detectors."""

from __future__ import annotations

from pathlib import Path

from migraid.analysis.issues import (
    Severity,
    detect_circular_deps,
    detect_conflicting_leaves,
    detect_dangling_dependencies,
    detect_incomplete_squash,
    detect_merge_migrations,
    detect_missing_reverse_code,
    detect_nondeterministic_deps,
    detect_numbering_issues,
    run_all_detectors,
)
from migraid.analysis.loader import MigrationAnalyzer


def _analyzer_from_dir(app: str, mig_dir: Path) -> MigrationAnalyzer:
    return MigrationAnalyzer(app_dirs=[(app, mig_dir)])


def test_detect_conflicting_leaves(conflict_scenario: Path) -> None:
    analyzer = _analyzer_from_dir("myapp", conflict_scenario)
    issues = detect_conflicting_leaves(analyzer)
    assert len(issues) == 1
    assert issues[0].code == "E001"
    assert issues[0].severity == Severity.ERROR
    assert issues[0].fixable is True


def test_no_conflict_in_linear_chain(simple_linear: Path) -> None:
    analyzer = _analyzer_from_dir("testapp", simple_linear)
    issues = detect_conflicting_leaves(analyzer)
    assert issues == []


def test_detect_circular_deps(circular_dep: Path) -> None:
    analyzer = _analyzer_from_dir("circapp", circular_dep)
    issues = detect_circular_deps(analyzer)
    assert len(issues) >= 1
    assert issues[0].code == "E002"
    assert issues[0].severity == Severity.ERROR


def test_detect_numbering_issues(numbering_gap: Path) -> None:
    analyzer = _analyzer_from_dir("gapapp", numbering_gap)
    issues = detect_numbering_issues(analyzer)
    assert any(i.code == "E003" for i in issues)
    e003 = [i for i in issues if i.code == "E003"]
    assert len(e003) >= 1


def test_no_numbering_issues_clean(simple_linear: Path) -> None:
    analyzer = _analyzer_from_dir("testapp", simple_linear)
    issues = detect_numbering_issues(analyzer)
    assert issues == []


def test_detect_dangling_dependencies(dangling_dep: Path) -> None:
    analyzer = _analyzer_from_dir("dangapp", dangling_dep)
    issues = detect_dangling_dependencies(analyzer)
    assert len(issues) == 1
    assert issues[0].code == "E004"
    assert issues[0].migration == "0002_add_field"


def test_detect_missing_reverse_code(runpython_no_reverse: Path) -> None:
    analyzer = _analyzer_from_dir("rpapp", runpython_no_reverse)
    issues = detect_missing_reverse_code(analyzer)
    assert len(issues) == 1
    assert issues[0].code == "W002"


def test_no_w002_with_noop(runpython_with_reverse: Path) -> None:
    analyzer = _analyzer_from_dir("rpapp", runpython_with_reverse)
    issues = detect_missing_reverse_code(analyzer)
    assert issues == []


def test_detect_incomplete_squash(squash_incomplete: Path) -> None:
    analyzer = _analyzer_from_dir("sqapp", squash_incomplete)
    issues = detect_incomplete_squash(analyzer)
    assert len(issues) == 1
    assert issues[0].code == "W003"


def test_detect_merge_migrations(tmp_path: Path) -> None:
    from tests.conftest import write_migration

    d = tmp_path / "mapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_branch_a", [("mapp", "0001_initial")])
    write_migration(d, "0002_branch_b", [("mapp", "0001_initial")])
    merge_content = """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("mapp", "0002_branch_a"),
        ("mapp", "0002_branch_b"),
    ]
    operations = []
"""
    (d / "0003_merge_0002.py").write_text(merge_content)
    analyzer = _analyzer_from_dir("mapp", d)
    issues = detect_merge_migrations(analyzer)
    assert any(i.code == "W004" for i in issues)


def test_detect_nondeterministic_deps(tmp_path: Path) -> None:
    d = tmp_path / "ndapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    content = """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("otherapp", "0002_step"),
        ("otherapp", "0001_initial"),
    ]
    operations = []
"""
    (d / "0001_initial.py").write_text(content)
    analyzer = _analyzer_from_dir("ndapp", d)
    issues = detect_nondeterministic_deps(analyzer)
    assert any(i.code == "W005" for i in issues)


def test_run_all_detectors_no_db(simple_linear: Path) -> None:
    analyzer = _analyzer_from_dir("testapp", simple_linear)
    # No DB connection — W001/I002 detectors are skipped
    issues = run_all_detectors(analyzer)
    # Should have no ERROR issues on a clean linear chain
    errors = [i for i in issues if i.severity == Severity.ERROR]
    assert errors == []


def test_run_all_detectors_with_conflicts(conflict_scenario: Path) -> None:
    analyzer = _analyzer_from_dir("myapp", conflict_scenario)
    issues = run_all_detectors(analyzer)
    codes = {i.code for i in issues}
    assert "E001" in codes
    # Sorted by severity
    assert issues[0].severity == Severity.ERROR


def test_run_all_detectors_app_filter(tmp_path: Path) -> None:
    from tests.conftest import write_migration

    d_a = tmp_path / "appa" / "migrations"
    d_b = tmp_path / "appb" / "migrations"
    d_a.mkdir(parents=True)
    d_b.mkdir(parents=True)
    (d_a / "__init__.py").write_text("")
    (d_b / "__init__.py").write_text("")
    write_migration(d_a, "0001_initial", [])
    write_migration(d_a, "0003_gap", [("appa", "0001_initial")])
    write_migration(d_b, "0001_initial", [])

    analyzer = MigrationAnalyzer(app_dirs=[("appa", d_a), ("appb", d_b)])
    issues = run_all_detectors(analyzer, app="appa")
    assert all(i.app == "appa" for i in issues)
