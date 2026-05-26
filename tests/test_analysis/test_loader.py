"""Tests for MigrationAnalyzer (Tier-2 loader facade)."""

from __future__ import annotations

from pathlib import Path

import pytest

from migraid.analysis.loader import MigrationAnalyzer
from tests.conftest import write_migration


def test_nodes_returns_static_graph(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])
    write_migration(d, "0002_step", [("myapp", "0001_initial")])

    analyzer = MigrationAnalyzer(app_dirs=[("myapp", d)])
    nodes = analyzer.nodes

    assert ("myapp", "0001_initial") in nodes
    assert ("myapp", "0002_step") in nodes


def test_reload_refreshes_nodes(tmp_path: Path) -> None:
    d = tmp_path / "myapp" / "migrations"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    write_migration(d, "0001_initial", [])

    analyzer = MigrationAnalyzer(app_dirs=[("myapp", d)])
    assert len(analyzer.nodes) == 1

    write_migration(d, "0002_step", [("myapp", "0001_initial")])
    analyzer.reload()

    assert len(analyzer.nodes) == 2


def test_has_db_connection_without_connection() -> None:
    analyzer = MigrationAnalyzer(app_dirs=[], connection=None)
    assert analyzer.has_db_connection() is False


@pytest.mark.django_db
def test_has_db_connection_with_live_connection() -> None:
    from django.db import connection

    analyzer = MigrationAnalyzer(app_dirs=[], connection=connection)
    assert analyzer.has_db_connection() is True


@pytest.mark.django_db
def test_applied_migrations_returns_dict() -> None:
    from django.db import connection

    analyzer = MigrationAnalyzer(app_dirs=[], connection=connection)
    applied = analyzer.applied_migrations()
    assert isinstance(applied, dict)


def test_applied_migrations_without_connection() -> None:
    analyzer = MigrationAnalyzer(app_dirs=[], connection=None)
    applied = analyzer.applied_migrations()
    assert applied == {}


def test_live_load_error_is_none_when_no_connection() -> None:
    analyzer = MigrationAnalyzer(app_dirs=[], connection=None)
    assert analyzer.live_load_error is None
