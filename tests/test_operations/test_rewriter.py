"""Tests for the libcst-based dependency rewriter."""

from __future__ import annotations

from pathlib import Path

import pytest

from migraid.operations.rewriter import rewrite_dependencies, rewrite_dependencies_in_source


@pytest.mark.parametrize(
    "source,replacements,expected_fragment",
    [
        # Double-quoted simple
        (
            'dependencies = [("myapp", "0001_initial")]',
            {("myapp", "0001_initial"): ("myapp", "0002_initial")},
            '"myapp", "0002_initial"',
        ),
        # Single-quoted
        (
            "dependencies = [('myapp', '0001_initial')]",
            {("myapp", "0001_initial"): ("myapp", "0002_initial")},
            "'myapp', '0002_initial'",
        ),
        # Multi-line list
        (
            'dependencies = [\n    ("myapp", "0001_initial"),\n]',
            {("myapp", "0001_initial"): ("myapp", "0002_initial")},
            '"myapp", "0002_initial"',
        ),
        # No match — unchanged
        (
            'dependencies = [("myapp", "0001_initial")]',
            {("myapp", "0099_other"): ("myapp", "0099_renamed")},
            '"myapp", "0001_initial"',
        ),
    ],
)
def test_rewrite_dependencies_in_source(
    source: str,
    replacements: dict[tuple[str, str], tuple[str, str]],
    expected_fragment: str,
) -> None:
    full_source = f"""\
from django.db import migrations


class Migration(migrations.Migration):
    {source}
    operations = []
"""
    result = rewrite_dependencies_in_source(full_source, replacements)
    assert expected_fragment in result


def test_rewrite_preserves_formatting() -> None:
    source = """\
from django.db import migrations


class Migration(migrations.Migration):
    # This comment should be preserved
    dependencies = [
        ("myapp", "0001_initial"),  # inline comment
    ]
    operations = []
"""
    result = rewrite_dependencies_in_source(
        source, {("myapp", "0001_initial"): ("myapp", "0002_initial")}
    )
    assert "# This comment should be preserved" in result
    assert "# inline comment" in result
    assert '"myapp", "0002_initial"' in result


def test_rewrite_empty_replacements() -> None:
    source = 'class Migration:\n    dependencies = [("a", "0001")]\n'
    result = rewrite_dependencies_in_source(source, {})
    assert result == source


def test_rewrite_from_file(tmp_path: Path) -> None:
    path = tmp_path / "0002_step.py"
    path.write_text(
        """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("myapp", "0001_initial")]
    operations = []
""",
        encoding="utf-8",
    )
    result = rewrite_dependencies(path, {("myapp", "0001_initial"): ("myapp", "0002_prev")})
    assert '"myapp", "0002_prev"' in result


def test_rewrite_run_before() -> None:
    source = """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []
    run_before = [("myapp", "0003_step")]
    operations = []
"""
    result = rewrite_dependencies_in_source(
        source, {("myapp", "0003_step"): ("myapp", "0004_step")}
    )
    assert '"myapp", "0004_step"' in result


def test_rewrite_replaces() -> None:
    source = """\
from django.db import migrations


class Migration(migrations.Migration):
    replaces = [("myapp", "0001_initial"), ("myapp", "0002_step")]
    dependencies = []
    operations = []
"""
    result = rewrite_dependencies_in_source(
        source, {("myapp", "0001_initial"): ("myapp", "0001_squashed")}
    )
    assert '"myapp", "0001_squashed"' in result
    # Other entry unchanged
    assert '"myapp", "0002_step"' in result


def test_rewrite_does_not_touch_outside_migration_class() -> None:
    source = """\
from django.db import migrations

# Module-level reference should NOT be replaced
MY_DEPS = [("myapp", "0001_initial")]


class Migration(migrations.Migration):
    dependencies = [("myapp", "0001_initial")]
    operations = []
"""
    result = rewrite_dependencies_in_source(
        source, {("myapp", "0001_initial"): ("myapp", "0002_new")}
    )
    # The module-level tuple should be unchanged
    # (The Migration class dependency IS updated)
    lines = result.split("\n")
    module_level_line = next(ln for ln in lines if "MY_DEPS" in ln)
    assert "0001_initial" in module_level_line
