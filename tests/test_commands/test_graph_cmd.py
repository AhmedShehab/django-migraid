"""Integration tests for the graph subcommand."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_graph_ascii_testapp() -> None:
    out = StringIO()
    call_command("migraid", "graph", "testapp", stdout=out)
    output = out.getvalue()
    assert "testapp" in output
    assert "0001_initial" in output


@pytest.mark.django_db
def test_graph_mermaid_format() -> None:
    out = StringIO()
    call_command("migraid", "graph", "testapp", "--format", "mermaid", stdout=out)
    output = out.getvalue()
    assert "graph TD" in output
    assert "testapp_0001_initial" in output


@pytest.mark.django_db
def test_graph_dot_format() -> None:
    out = StringIO()
    call_command("migraid", "graph", "testapp", "--format", "dot", stdout=out)
    output = out.getvalue()
    assert "digraph migrations" in output


@pytest.mark.django_db
def test_graph_output_to_file(tmp_path) -> None:
    out_file = tmp_path / "graph.txt"
    call_command(
        "migraid", "graph", "testapp",
        "--format", "ascii",
        "--output", str(out_file),
    )
    assert out_file.exists()
    content = out_file.read_text()
    assert "testapp" in content


@pytest.mark.django_db
def test_graph_all_apps() -> None:
    """Running without --app produces output for all apps."""
    out = StringIO()
    call_command("migraid", "graph", "--format", "mermaid", stdout=out)
    output = out.getvalue()
    assert "graph TD" in output
