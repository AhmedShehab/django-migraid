"""Shared pytest fixtures for django-migraid tests."""

from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION_TEMPLATE = """\
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = {dependencies!r}
    operations = {operations}
"""

RUNPYTHON_TEMPLATE = """\
from django.db import migrations


def forward(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = {dependencies!r}
    operations = [
        migrations.RunPython(forward{reverse}),
    ]
"""


def write_migration(
    directory: Path,
    name: str,
    dependencies: list[tuple[str, str]] | None = None,
    operations: str = "[]",
    content: str | None = None,
) -> Path:
    """Write a synthetic migration file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    init = directory / "__init__.py"
    if not init.exists():
        init.write_text("")
    path = directory / f"{name}.py"
    if content is not None:
        path.write_text(content)
    else:
        deps = dependencies or []
        path.write_text(MIGRATION_TEMPLATE.format(dependencies=deps, operations=operations))
    return path


@pytest.fixture
def mig_dir(tmp_path: Path) -> Path:
    """A fresh migrations directory for 'testapp'."""
    d = tmp_path / "testapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    return d


@pytest.fixture
def simple_linear(mig_dir: Path) -> Path:
    """0001 → 0002 → 0003 linear chain."""
    write_migration(mig_dir, "0001_initial", [])
    write_migration(mig_dir, "0002_add_field", [("testapp", "0001_initial")])
    write_migration(mig_dir, "0003_add_other", [("testapp", "0002_add_field")])
    return mig_dir


@pytest.fixture
def conflict_scenario(tmp_path: Path) -> Path:
    """Two migrations with the same parent (E001 conflict)."""
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_add_email", [("myapp", "0001_initial")])
    write_migration(d, "0002_add_phone", [("myapp", "0001_initial")])
    return d


@pytest.fixture
def numbering_gap(tmp_path: Path) -> Path:
    """0001 → 0003 (gap at 0002), E003."""
    d = tmp_path / "gapapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0003_add_field", [("gapapp", "0001_initial")])
    return d


@pytest.fixture
def circular_dep(tmp_path: Path) -> Path:
    """Migration A depends on B and B depends on A (E002)."""
    d = tmp_path / "circapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [("circapp", "0002_step")])
    write_migration(d, "0002_step", [("circapp", "0001_initial")])
    return d


@pytest.fixture
def dangling_dep(tmp_path: Path) -> Path:
    """Migration depends on a migration that doesn't exist (E004)."""
    d = tmp_path / "dangapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_add_field", [("dangapp", "0099_deleted")])
    return d


@pytest.fixture
def runpython_no_reverse(tmp_path: Path) -> Path:
    """RunPython without reverse_code (W002)."""
    d = tmp_path / "rpapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    content = RUNPYTHON_TEMPLATE.format(
        dependencies=[("rpapp", "0001_initial")],
        reverse="",
    )
    (d / "0002_data_migration.py").write_text(content)
    return d


@pytest.fixture
def runpython_with_reverse(tmp_path: Path) -> Path:
    """RunPython with reverse_code (no W002)."""
    d = tmp_path / "rpapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    content = RUNPYTHON_TEMPLATE.format(
        dependencies=[("rpapp", "0001_initial")],
        reverse=", migrations.RunPython.noop",
    )
    (d / "0002_data_migration.py").write_text(content)
    return d


@pytest.fixture
def squash_incomplete(tmp_path: Path) -> Path:
    """Squashed migration with old files still present (W003)."""
    d = tmp_path / "sqapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_add_field", [("sqapp", "0001_initial")])
    squash_content = """\
from django.db import migrations


class Migration(migrations.Migration):
    replaces = [("sqapp", "0001_initial"), ("sqapp", "0002_add_field")]
    dependencies = []
    operations = []
"""
    (d / "0001_0002_squashed.py").write_text(squash_content)
    return d
