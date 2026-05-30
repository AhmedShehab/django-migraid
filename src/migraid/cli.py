"""Standalone console-script entry point for migraid.

This lets users run ``migraid <subcommand>`` directly from the shell after
``pip install django-migraid`` **without** adding ``"migraid"`` to
``INSTALLED_APPS``. It bootstraps Django itself, injects the app into
``INSTALLED_APPS`` in memory, then delegates to the existing ``migraid``
management command. The standard ``python manage.py migraid ...`` flow is
unaffected and keeps working when the app is installed the usual way.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_NAME = "migraid"

_SETTINGS_RE = re.compile(
    r"""os\.environ\.setdefault\(\s*['"]DJANGO_SETTINGS_MODULE['"]\s*,\s*['"]([^'"]+)['"]"""
)


def _find_manage_py(start: Path | None = None) -> Path | None:
    """Walk upward from ``start`` (or the cwd) to locate a ``manage.py`` file."""
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / "manage.py"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _settings_from_manage_py(manage_py: Path) -> str | None:
    """Extract the ``DJANGO_SETTINGS_MODULE`` value from a ``manage.py`` file."""
    try:
        text = manage_py.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _SETTINGS_RE.search(text)
    return match.group(1) if match else None


def _extract_settings_flag(args: list[str]) -> str | None:
    """Return the value of a ``--settings`` flag in ``args``, if present."""
    for i, arg in enumerate(args):
        if arg == "--settings" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--settings="):
            return arg.split("=", 1)[1]
    return None


def _bootstrap_settings(args: list[str]) -> None:
    """Ensure ``DJANGO_SETTINGS_MODULE`` is set and the project root is importable.

    Resolution order: ``--settings`` flag > existing env var > ``manage.py``
    discovery. Exits with a friendly message if none of these resolve.
    """
    explicit = _extract_settings_flag(args)
    if explicit:
        os.environ["DJANGO_SETTINGS_MODULE"] = explicit

    manage_py = _find_manage_py()
    if manage_py is not None:
        # The settings module is usually importable relative to the project root.
        project_root = str(manage_py.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

    if os.environ.get("DJANGO_SETTINGS_MODULE"):
        return

    if manage_py is not None:
        module = _settings_from_manage_py(manage_py)
        if module:
            os.environ["DJANGO_SETTINGS_MODULE"] = module
            return

    sys.stderr.write(
        "migraid: could not determine your Django settings.\n"
        "Set DJANGO_SETTINGS_MODULE, pass --settings <module>, or run from a\n"
        "directory containing your project's manage.py.\n"
    )
    raise SystemExit(1)


def _inject_app() -> None:
    """Add migraid to ``INSTALLED_APPS`` in memory before ``django.setup()`` runs.

    Accessing ``settings.INSTALLED_APPS`` lazily loads the user's settings
    module; reassigning it overrides the value before the app registry reads it.
    The check is idempotent and also tolerates an explicit ``AppConfig`` path
    (e.g. ``"migraid.apps.MigraidConfig"``) to avoid a duplicate-label error.
    """
    from django.conf import settings

    already = any(
        app == APP_NAME or app.startswith(f"{APP_NAME}.") for app in settings.INSTALLED_APPS
    )
    if not already:
        settings.INSTALLED_APPS = [*settings.INSTALLED_APPS, APP_NAME]


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``migraid`` console script."""
    argv = list(sys.argv if argv is None else argv)
    user_args = argv[1:]

    _bootstrap_settings(user_args)
    _inject_app()

    # Re-shape argv into the management-command form: ``<prog> migraid <args>``.
    # Inserting the literal "migraid" also keeps the recursion guard in
    # MigraidConfig.ready() working for ``migraid db ...`` invocations.
    sys.argv = [argv[0], APP_NAME, *user_args]

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
