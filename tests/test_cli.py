"""Tests for the standalone ``migraid`` console-script entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from migraid import cli

MANAGE_PY = """\
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
"""


class FakeSettings:
    def __init__(self, installed_apps: list[str]) -> None:
        self.INSTALLED_APPS = installed_apps


def test_find_manage_py_walks_upward(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text(MANAGE_PY)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert cli._find_manage_py(nested) == (tmp_path / "manage.py").resolve()


def test_find_manage_py_missing(tmp_path: Path) -> None:
    assert cli._find_manage_py(tmp_path) is None


def test_settings_from_manage_py(tmp_path: Path) -> None:
    manage_py = tmp_path / "manage.py"
    manage_py.write_text(MANAGE_PY)
    assert cli._settings_from_manage_py(manage_py) == "myproject.settings"


def test_settings_from_manage_py_no_match(tmp_path: Path) -> None:
    manage_py = tmp_path / "manage.py"
    manage_py.write_text("print('hello')\n")
    assert cli._settings_from_manage_py(manage_py) is None


def test_extract_settings_flag_space() -> None:
    assert cli._extract_settings_flag(["doctor", "--settings", "foo.bar"]) == "foo.bar"


def test_extract_settings_flag_equals() -> None:
    assert cli._extract_settings_flag(["doctor", "--settings=foo.bar"]) == "foo.bar"


def test_extract_settings_flag_absent() -> None:
    assert cli._extract_settings_flag(["doctor"]) is None


def test_bootstrap_settings_uses_env(tmp_path: Path) -> None:
    with (
        patch.object(cli, "_find_manage_py", return_value=None),
        patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "already.set"}),
    ):
        cli._bootstrap_settings([])  # should not raise
        assert os.environ["DJANGO_SETTINGS_MODULE"] == "already.set"


def test_bootstrap_settings_explicit_flag_wins(tmp_path: Path) -> None:
    with (
        patch.object(cli, "_find_manage_py", return_value=None),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        cli._bootstrap_settings(["doctor", "--settings", "explicit.settings"])
        assert os.environ["DJANGO_SETTINGS_MODULE"] == "explicit.settings"


def test_bootstrap_settings_from_manage_py(tmp_path: Path) -> None:
    manage_py = tmp_path / "manage.py"
    manage_py.write_text(MANAGE_PY)
    with (
        patch.object(cli, "_find_manage_py", return_value=manage_py),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        cli._bootstrap_settings([])
        assert os.environ["DJANGO_SETTINGS_MODULE"] == "myproject.settings"


def test_bootstrap_settings_missing_exits() -> None:
    with (
        patch.object(cli, "_find_manage_py", return_value=None),
        patch.dict(os.environ, {}, clear=False),
        pytest.raises(SystemExit) as exc,
    ):
        os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        cli._bootstrap_settings([])
    assert exc.value.code == 1


def test_inject_app_appends_when_absent() -> None:
    fake = FakeSettings(["django.contrib.auth"])
    with patch("django.conf.settings", fake):
        cli._inject_app()
    assert fake.INSTALLED_APPS == ["django.contrib.auth", "migraid"]


def test_inject_app_idempotent() -> None:
    fake = FakeSettings(["migraid", "django.contrib.auth"])
    with patch("django.conf.settings", fake):
        cli._inject_app()
    assert fake.INSTALLED_APPS.count("migraid") == 1


def test_inject_app_tolerates_appconfig_path() -> None:
    fake = FakeSettings(["migraid.apps.MigraidConfig"])
    with patch("django.conf.settings", fake):
        cli._inject_app()
    assert fake.INSTALLED_APPS == ["migraid.apps.MigraidConfig"]


def test_main_delegates_to_management_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_execute(argv: list[str]) -> None:
        # Capture the reshaped process argv as the management command would see it.
        captured["argv"] = list(sys.argv)

    monkeypatch.setattr(sys, "argv", ["migraid"])
    with (
        patch.object(cli, "_bootstrap_settings"),
        patch.object(cli, "_inject_app"),
        patch("django.core.management.execute_from_command_line", fake_execute),
    ):
        cli.main(["migraid", "doctor", "--format", "json"])

    # main() reshapes argv into management-command form so ready()'s recursion
    # guard sees the literal "migraid".
    assert captured["argv"] == ["migraid", "migraid", "doctor", "--format", "json"]


def test_main_inserts_migraid_for_db_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(sys, "argv", ["migraid"])
    with (
        patch.object(cli, "_bootstrap_settings"),
        patch.object(cli, "_inject_app"),
        patch(
            "django.core.management.execute_from_command_line",
            lambda argv: captured.setdefault("argv", list(argv)),
        ),
    ):
        cli.main(["migraid", "db", "add"])

    assert captured["argv"] == ["migraid", "migraid", "db", "add"]
