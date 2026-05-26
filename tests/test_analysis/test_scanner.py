"""Tests for the static migration file scanner."""

from __future__ import annotations

from pathlib import Path

from migraid.analysis.scanner import (
    MigrationNode,
    parse_migration_file,
    scan_app_migrations,
    scan_dirs,
)

SIMPLE_MIGRATION = """\
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Foo", fields=[]),
    ]
"""

MIGRATION_WITH_DEPS = """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("myapp", "0001_initial"),
        ("otherapp", "0003_step"),
    ]
    operations = []
"""

RUNPYTHON_NO_REVERSE = """\
from django.db import migrations


def forward(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("myapp", "0001_initial")]
    operations = [
        migrations.RunPython(forward),
    ]
"""

RUNPYTHON_WITH_NOOP = """\
from django.db import migrations


def forward(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("myapp", "0001_initial")]
    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
"""

RUNSQL_NO_REVERSE = """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []
    operations = [
        migrations.RunSQL("SELECT 1"),
    ]
"""

SQUASH_MIGRATION = """\
from django.db import migrations


class Migration(migrations.Migration):
    replaces = [("myapp", "0001_initial"), ("myapp", "0002_add_field")]
    dependencies = []
    operations = []
"""

SINGLE_QUOTED = """\
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('myapp', '0001_initial'),
    ]
    operations = []
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / f"{name}.py"
    p.write_text(content)
    return p


def test_parse_initial_migration(tmp_path: Path) -> None:
    path = _write(tmp_path, "0001_initial", SIMPLE_MIGRATION)
    node = parse_migration_file("myapp", "0001_initial", path)
    assert node is not None
    assert node.app_label == "myapp"
    assert node.name == "0001_initial"
    assert node.initial is True
    assert node.dependencies == []
    assert len(node.operations) == 1
    assert node.operations[0].name == "CreateModel"


def test_parse_migration_with_deps(tmp_path: Path) -> None:
    path = _write(tmp_path, "0002_step", MIGRATION_WITH_DEPS)
    node = parse_migration_file("myapp", "0002_step", path)
    assert node is not None
    assert node.dependencies == [("myapp", "0001_initial"), ("otherapp", "0003_step")]


def test_parse_single_quoted_deps(tmp_path: Path) -> None:
    path = _write(tmp_path, "0002_step", SINGLE_QUOTED)
    node = parse_migration_file("myapp", "0002_step", path)
    assert node is not None
    assert node.dependencies == [("myapp", "0001_initial")]


def test_runpython_no_reverse(tmp_path: Path) -> None:
    path = _write(tmp_path, "0002_data", RUNPYTHON_NO_REVERSE)
    node = parse_migration_file("myapp", "0002_data", path)
    assert node is not None
    assert len(node.operations) == 1
    assert node.operations[0].name == "RunPython"
    assert node.operations[0].has_reverse is False


def test_runpython_with_noop(tmp_path: Path) -> None:
    path = _write(tmp_path, "0002_data", RUNPYTHON_WITH_NOOP)
    node = parse_migration_file("myapp", "0002_data", path)
    assert node is not None
    assert node.operations[0].has_reverse is True


def test_runsql_no_reverse(tmp_path: Path) -> None:
    path = _write(tmp_path, "0002_sql", RUNSQL_NO_REVERSE)
    node = parse_migration_file("myapp", "0002_sql", path)
    assert node is not None
    assert node.operations[0].name == "RunSQL"
    assert node.operations[0].has_reverse is False


def test_parse_squash_migration(tmp_path: Path) -> None:
    path = _write(tmp_path, "0001_squashed", SQUASH_MIGRATION)
    node = parse_migration_file("myapp", "0001_squashed", path)
    assert node is not None
    assert node.replaces == [("myapp", "0001_initial"), ("myapp", "0002_add_field")]


def test_parse_returns_none_on_invalid_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.py"
    path.write_text("this is not valid python %%% !!!")
    node = parse_migration_file("myapp", "bad", path)
    assert node is None


def test_node_number_property() -> None:
    node = MigrationNode(
        app_label="myapp",
        name="0042_add_field",
        path=Path("/fake"),
    )
    assert node.number == 42
    assert node.name_suffix == "add_field"


def test_node_number_none_for_non_numeric() -> None:
    node = MigrationNode(app_label="myapp", name="initial", path=Path("/fake"))
    assert node.number is None


def test_scan_app_migrations(tmp_path: Path) -> None:
    mig_dir = tmp_path / "myapp" / "migrations"
    mig_dir.mkdir(parents=True)
    (mig_dir / "__init__.py").write_text("")
    _write(mig_dir, "0001_initial", SIMPLE_MIGRATION)
    _write(mig_dir, "0002_step", MIGRATION_WITH_DEPS)
    nodes = scan_app_migrations("myapp", mig_dir)
    assert len(nodes) == 2
    assert nodes[0].name == "0001_initial"
    assert nodes[1].name == "0002_step"


def test_scan_app_ignores_init(tmp_path: Path) -> None:
    mig_dir = tmp_path / "myapp" / "migrations"
    mig_dir.mkdir(parents=True)
    (mig_dir / "__init__.py").write_text("# init")
    _write(mig_dir, "0001_initial", SIMPLE_MIGRATION)
    nodes = scan_app_migrations("myapp", mig_dir)
    assert len(nodes) == 1


def test_scan_dirs_multiple_apps(tmp_path: Path) -> None:
    for app in ("app_a", "app_b"):
        d = tmp_path / app / "migrations"
        d.mkdir(parents=True)
        (d / "__init__.py").write_text("")
        _write(d, "0001_initial", SIMPLE_MIGRATION)

    nodes = scan_dirs(
        [
            ("app_a", tmp_path / "app_a" / "migrations"),
            ("app_b", tmp_path / "app_b" / "migrations"),
        ]
    )
    assert len(nodes) == 2
    assert ("app_a", "0001_initial") in nodes
    assert ("app_b", "0001_initial") in nodes
