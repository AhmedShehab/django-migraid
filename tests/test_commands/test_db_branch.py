"""Tests for the `migraid db` subcommand and branch_db operations module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from migraid.operations.branch_db import (
    BranchDBConfig,
    BranchDBEntry,
    _build_postgres_dsn,
    create_database,
    current_git_branch,
    derive_new_db_config,
    drop_database,
    find_git_root,
    local_git_branch_names,
    slugify_branch,
)

# ---------------------------------------------------------------------------
# slugify_branch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch,expected",
    [
        ("main", "main"),
        ("feature/add-login", "feature_add_login"),
        ("bugfix/FOO-123", "bugfix_foo_123"),
        ("release/1.2.3", "release_1_2_3"),
        ("/leading/slash", "leading_slash"),
        ("trailing/", "trailing"),
        ("a" * 60, "a" * 50),
        ("", "branch"),
        ("---", "branch"),
    ],
)
def test_slugify_branch(branch: str, expected: str) -> None:
    assert slugify_branch(branch) == expected


# ---------------------------------------------------------------------------
# derive_new_db_config
# ---------------------------------------------------------------------------


def test_derive_sqlite_file_path() -> None:
    base = {"ENGINE": "django.db.backends.sqlite3", "NAME": "/project/db.sqlite3"}
    result = derive_new_db_config(base, "feat_login")
    assert result["NAME"] == "/project/db_feat_login.sqlite3"
    assert result["ENGINE"] == base["ENGINE"]


def test_derive_sqlite_memory_uses_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    base = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    result = derive_new_db_config(base, "my_branch")
    assert result["NAME"] == str(tmp_path / "db_my_branch.sqlite3")


def test_derive_postgres_name() -> None:
    base = {"ENGINE": "django.db.backends.postgresql", "NAME": "myapp", "HOST": "localhost"}
    result = derive_new_db_config(base, "feature_foo")
    assert result["NAME"] == "myapp_feature_foo"
    assert result["HOST"] == "localhost"


# ---------------------------------------------------------------------------
# BranchDBConfig: load / save / round-trip
# ---------------------------------------------------------------------------


def test_config_load_missing_file(tmp_path: Path) -> None:
    cfg = BranchDBConfig.load(tmp_path)
    assert cfg.branch_dbs == {}
    assert cfg.config_path == tmp_path / ".migraid" / "config.json"


def test_config_round_trip(tmp_path: Path) -> None:
    cfg = BranchDBConfig.load(tmp_path)
    db_config = {"ENGINE": "django.db.backends.sqlite3", "NAME": "/tmp/db_feat.sqlite3"}
    cfg.register("feature/foo", BranchDBEntry(alias="feature_foo", db_config=db_config))
    cfg.save()

    loaded = BranchDBConfig.load(tmp_path)
    assert "feature/foo" in loaded.branch_dbs
    entry = loaded.branch_dbs["feature/foo"]
    assert entry.alias == "feature_foo"
    assert entry.db_config == db_config


def test_config_unregister(tmp_path: Path) -> None:
    cfg = BranchDBConfig.load(tmp_path)
    cfg.register("main", BranchDBEntry(alias="default", db_config=None))
    cfg.register("feature/x", BranchDBEntry(alias="feature_x", db_config={}))
    cfg.unregister("feature/x")
    assert "feature/x" not in cfg.branch_dbs
    assert "main" in cfg.branch_dbs


def test_config_stale_branches(tmp_path: Path) -> None:
    cfg = BranchDBConfig.load(tmp_path)
    cfg.register("main", BranchDBEntry(alias="default", db_config=None))
    cfg.register("feature/a", BranchDBEntry(alias="feature_a", db_config={}))
    cfg.register("feature/b", BranchDBEntry(alias="feature_b", db_config={}))

    stale = cfg.stale_branches({"main"})
    assert stale == ["feature/a", "feature/b"]


def test_config_inject_all(tmp_path: Path) -> None:
    from django.db import connections

    db_config = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    cfg = BranchDBConfig.load(tmp_path)
    cfg.register("feature/inject", BranchDBEntry(alias="test_inject_alias", db_config=db_config))

    cfg.inject_all()
    assert "test_inject_alias" in connections.databases
    # Cleanup
    connections.databases.pop("test_inject_alias", None)


def test_config_inject_skips_none_db_config(tmp_path: Path) -> None:
    from django.db import connections

    cfg = BranchDBConfig.load(tmp_path)
    # db_config=None means the alias is already in Django settings
    cfg.register("main", BranchDBEntry(alias="default", db_config=None))
    before = set(connections.databases.keys())
    cfg.inject_all()
    # No new alias should be added
    assert set(connections.databases.keys()) == before


# ---------------------------------------------------------------------------
# drop_database (SQLite)
# ---------------------------------------------------------------------------


def test_drop_database_sqlite_deletes_file(tmp_path: Path) -> None:
    db_file = tmp_path / "test_drop.sqlite3"
    db_file.write_bytes(b"")
    assert db_file.exists()
    drop_database({"ENGINE": "django.db.backends.sqlite3", "NAME": str(db_file)})
    assert not db_file.exists()


def test_drop_database_sqlite_missing_file_is_noop(tmp_path: Path) -> None:
    db_file = tmp_path / "nonexistent.sqlite3"
    # Should not raise even if the file doesn't exist
    drop_database({"ENGINE": "django.db.backends.sqlite3", "NAME": str(db_file)})


def test_drop_database_sqlite_memory_is_noop() -> None:
    drop_database({"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"})


# ---------------------------------------------------------------------------
# `migraid db add` integration
# ---------------------------------------------------------------------------


def _make_git_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_db_add_creates_sqlite_file(tmp_path: Path) -> None:
    """db add saves config and calls migrate for the derived SQLite alias."""
    from django.db import connections

    git_root = _make_git_root(tmp_path)
    base_db = tmp_path / "base.sqlite3"
    connections.databases["test_base"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(base_db),
    }

    migrate_calls: list[tuple] = []

    def _fake_migrate(*args: Any, **kwargs: Any) -> None:
        migrate_calls.append((args, kwargs))

    try:
        with (
            patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
            patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
            patch(
                "migraid.operations.branch_db.current_git_branch",
                return_value="feature/sqlite-test",
            ),
            patch(
                "migraid.management.commands.migraid.current_git_branch",
                return_value="feature/sqlite-test",
            ),
            patch("django.core.management.call_command", side_effect=_fake_migrate),
        ):
            call_command("migraid", "db", "add", "--database", "test_base", "--yes")

        cfg = BranchDBConfig.load(git_root)
        assert "feature/sqlite-test" in cfg.branch_dbs
        entry = cfg.branch_dbs["feature/sqlite-test"]
        assert entry.alias == "feature_sqlite_test"
        # Verify migrate was invoked for the new alias
        assert any(kw.get("database") == "feature_sqlite_test" for _, kw in migrate_calls)
    finally:
        connections.databases.pop("test_base", None)
        connections.databases.pop("feature_sqlite_test", None)


def test_db_add_alias_override(tmp_path: Path) -> None:
    """--alias overrides the slugified branch name."""
    from django.db import connections

    git_root = _make_git_root(tmp_path)
    base_db = tmp_path / "base2.sqlite3"
    connections.databases["test_base2"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(base_db),
    }

    try:
        with (
            patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
            patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
            patch("migraid.operations.branch_db.current_git_branch", return_value="main"),
            patch("migraid.management.commands.migraid.current_git_branch", return_value="main"),
            patch("django.core.management.call_command"),
        ):
            call_command(
                "migraid",
                "db",
                "add",
                "--database",
                "test_base2",
                "--alias",
                "my_custom_alias",
                "--yes",
            )

        cfg = BranchDBConfig.load(git_root)
        assert cfg.branch_dbs["main"].alias == "my_custom_alias"
    finally:
        connections.databases.pop("test_base2", None)
        connections.databases.pop("my_custom_alias", None)


def test_db_add_rejects_duplicate_branch(tmp_path: Path) -> None:
    from django.db import connections

    git_root = _make_git_root(tmp_path)
    base_db = tmp_path / "base3.sqlite3"
    connections.databases["test_base3"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(base_db),
    }

    # Pre-register the branch
    cfg = BranchDBConfig.load(git_root)
    cfg.register("feature/dup", BranchDBEntry(alias="feature_dup", db_config={}))
    cfg.save()

    try:
        with (
            patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
            patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
            patch("migraid.operations.branch_db.current_git_branch", return_value="feature/dup"),
            patch(
                "migraid.management.commands.migraid.current_git_branch",
                return_value="feature/dup",
            ),
            pytest.raises((CommandError, SystemExit)),
        ):
            call_command("migraid", "db", "add", "--database", "test_base3", "--yes")
    finally:
        connections.databases.pop("test_base3", None)


# ---------------------------------------------------------------------------
# `migraid db rm` integration
# ---------------------------------------------------------------------------


def test_db_rm_removes_entry_and_drops_file(tmp_path: Path) -> None:
    git_root = _make_git_root(tmp_path)
    db_file = tmp_path / "db_feat_rm.sqlite3"
    db_file.write_bytes(b"")

    cfg = BranchDBConfig.load(git_root)
    cfg.register(
        "feature/rm",
        BranchDBEntry(
            alias="feat_rm",
            db_config={"ENGINE": "django.db.backends.sqlite3", "NAME": str(db_file)},
        ),
    )
    cfg.save()

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.current_git_branch", return_value="main"),
        patch("migraid.management.commands.migraid.current_git_branch", return_value="main"),
    ):
        call_command("migraid", "db", "rm", "--branch", "feature/rm", "--yes")

    cfg_after = BranchDBConfig.load(git_root)
    assert "feature/rm" not in cfg_after.branch_dbs
    assert not db_file.exists()


def test_db_rm_blocks_current_branch_without_yes(tmp_path: Path) -> None:
    git_root = _make_git_root(tmp_path)
    db_file = tmp_path / "db_current.sqlite3"
    db_file.write_bytes(b"")

    cfg = BranchDBConfig.load(git_root)
    cfg.register(
        "main",
        BranchDBEntry(
            alias="main_db",
            db_config={"ENGINE": "django.db.backends.sqlite3", "NAME": str(db_file)},
        ),
    )
    cfg.save()

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.current_git_branch", return_value="main"),
        patch("migraid.management.commands.migraid.current_git_branch", return_value="main"),
        pytest.raises((CommandError, SystemExit)),
    ):
        # no --yes flag → should be blocked
        call_command("migraid", "db", "rm", "--branch", "main")


def test_db_rm_skips_drop_for_user_configured_alias(tmp_path: Path) -> None:
    """Entries with db_config=None (user-configured aliases) are just unregistered."""
    git_root = _make_git_root(tmp_path)

    cfg = BranchDBConfig.load(git_root)
    cfg.register("main", BranchDBEntry(alias="default", db_config=None))
    cfg.save()

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.current_git_branch", return_value="other"),
        patch("migraid.management.commands.migraid.current_git_branch", return_value="other"),
    ):
        call_command("migraid", "db", "rm", "--branch", "main", "--yes")

    cfg_after = BranchDBConfig.load(git_root)
    assert "main" not in cfg_after.branch_dbs


# ---------------------------------------------------------------------------
# `migraid db prune` integration
# ---------------------------------------------------------------------------


def test_db_prune_removes_stale_branches(tmp_path: Path) -> None:
    git_root = _make_git_root(tmp_path)
    stale_db = tmp_path / "db_stale.sqlite3"
    stale_db.write_bytes(b"")

    cfg = BranchDBConfig.load(git_root)
    cfg.register("main", BranchDBEntry(alias="default", db_config=None))
    cfg.register(
        "feature/old",
        BranchDBEntry(
            alias="feature_old",
            db_config={"ENGINE": "django.db.backends.sqlite3", "NAME": str(stale_db)},
        ),
    )
    cfg.save()

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.local_git_branch_names", return_value={"main"}),
        patch("migraid.management.commands.migraid.local_git_branch_names", return_value={"main"}),
    ):
        call_command("migraid", "db", "prune", "--yes")

    cfg_after = BranchDBConfig.load(git_root)
    assert "feature/old" not in cfg_after.branch_dbs
    assert "main" in cfg_after.branch_dbs
    assert not stale_db.exists()


def test_db_prune_dry_run_makes_no_changes(tmp_path: Path) -> None:
    git_root = _make_git_root(tmp_path)
    stale_db = tmp_path / "db_dry.sqlite3"
    stale_db.write_bytes(b"")

    cfg = BranchDBConfig.load(git_root)
    cfg.register(
        "feature/dry",
        BranchDBEntry(
            alias="feature_dry",
            db_config={"ENGINE": "django.db.backends.sqlite3", "NAME": str(stale_db)},
        ),
    )
    cfg.save()

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.local_git_branch_names", return_value=set()),
        patch("migraid.management.commands.migraid.local_git_branch_names", return_value=set()),
    ):
        call_command("migraid", "db", "prune", "--dry-run")

    cfg_after = BranchDBConfig.load(git_root)
    assert "feature/dry" in cfg_after.branch_dbs
    assert stale_db.exists()


def test_db_prune_nothing_to_do(tmp_path: Path) -> None:
    git_root = _make_git_root(tmp_path)

    cfg = BranchDBConfig.load(git_root)
    cfg.register("main", BranchDBEntry(alias="default", db_config=None))
    cfg.save()

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.local_git_branch_names", return_value={"main"}),
        patch("migraid.management.commands.migraid.local_git_branch_names", return_value={"main"}),
    ):
        # Should not raise
        call_command("migraid", "db", "prune", "--yes")


# ---------------------------------------------------------------------------
# `migraid db ls` integration
# ---------------------------------------------------------------------------


def test_db_ls_prints_table(tmp_path: Path) -> None:
    git_root = _make_git_root(tmp_path)

    cfg = BranchDBConfig.load(git_root)
    cfg.register("main", BranchDBEntry(alias="default", db_config=None))
    cfg.register(
        "feature/foo",
        BranchDBEntry(
            alias="feature_foo",
            db_config={
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": "/tmp/db_feature_foo.sqlite3",
            },
        ),
    )
    cfg.save()

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.current_git_branch", return_value="main"),
        patch("migraid.management.commands.migraid.current_git_branch", return_value="main"),
        patch(
            "migraid.operations.branch_db.local_git_branch_names",
            return_value={"main", "feature/foo"},
        ),
        patch(
            "migraid.management.commands.migraid.local_git_branch_names",
            return_value={"main", "feature/foo"},
        ),
    ):
        call_command("migraid", "db", "ls")


def test_db_ls_empty(tmp_path: Path) -> None:
    git_root = _make_git_root(tmp_path)

    with (
        patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
        patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
        patch("migraid.operations.branch_db.current_git_branch", return_value="main"),
        patch("migraid.management.commands.migraid.current_git_branch", return_value="main"),
    ):
        call_command("migraid", "db", "ls")


# ---------------------------------------------------------------------------
# execute() auto-resolve --database
# ---------------------------------------------------------------------------


def test_execute_auto_resolves_database_for_current_branch(tmp_path: Path) -> None:
    """When a branch is registered, commands with --database should auto-resolve it."""
    from django.db import connections

    git_root = _make_git_root(tmp_path)
    db_config = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    cfg = BranchDBConfig.load(git_root)
    cfg.register("feature/auto", BranchDBEntry(alias="auto_alias", db_config=db_config))
    cfg.save()

    connections.databases["auto_alias"] = db_config

    resolved_alias: list[str] = []

    from migraid.management.commands.migraid import Command

    original = Command._handle_prune

    def _capture_prune(_self: Any, opts: dict[str, Any]) -> None:
        resolved_alias.append(opts.get("database", "NOT_SET"))

    try:
        Command._handle_prune = _capture_prune  # type: ignore[method-assign]

        with (
            patch("migraid.operations.branch_db.find_git_root", return_value=git_root),
            patch("migraid.management.commands.migraid.find_git_root", return_value=git_root),
            patch("migraid.operations.branch_db.current_git_branch", return_value="feature/auto"),
            patch(
                "migraid.management.commands.migraid.current_git_branch",
                return_value="feature/auto",
            ),
        ):
            call_command("migraid", "prune")

        assert resolved_alias == ["auto_alias"]
    finally:
        Command._handle_prune = original  # type: ignore[method-assign]
        connections.databases.pop("auto_alias", None)


# ---------------------------------------------------------------------------
# BranchDBConfig.load — corrupt JSON
# ---------------------------------------------------------------------------


def test_config_load_corrupt_json(tmp_path: Path) -> None:
    config_dir = tmp_path / ".migraid"
    config_dir.mkdir()
    (config_dir / "config.json").write_text("not valid json {{{", encoding="utf-8")
    cfg = BranchDBConfig.load(tmp_path)
    assert cfg.branch_dbs == {}


# ---------------------------------------------------------------------------
# _build_postgres_dsn
# ---------------------------------------------------------------------------


def test_build_postgres_dsn_all_fields() -> None:
    config = {
        "HOST": "db.example.com",
        "PORT": 5432,
        "USER": "admin",
        "PASSWORD": "s3cr3t",
        "NAME": "mydb",
    }
    dsn = _build_postgres_dsn(config)
    assert "host=db.example.com" in dsn
    assert "port=5432" in dsn
    assert "user=admin" in dsn
    assert "password=s3cr3t" in dsn
    assert "dbname=mydb" in dsn


def test_build_postgres_dsn_empty() -> None:
    assert _build_postgres_dsn({}) == ""


def test_build_postgres_dsn_partial() -> None:
    dsn = _build_postgres_dsn({"HOST": "localhost", "NAME": "app"})
    assert "host=localhost" in dsn
    assert "dbname=app" in dsn
    assert "user" not in dsn


# ---------------------------------------------------------------------------
# create_database — Postgres path (mocked)
# ---------------------------------------------------------------------------


def _mock_psycopg2() -> MagicMock:
    mock = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    mock.connect.return_value = mock_conn
    mock.sql = MagicMock()
    mock.sql.SQL.return_value.format.return_value = "CREATE DATABASE ..."
    return mock


def test_create_database_postgres_calls_create() -> None:
    import sys

    mock_pg = _mock_psycopg2()
    mock_pg_sql = MagicMock()
    with patch.dict(sys.modules, {"psycopg2": mock_pg, "psycopg2.sql": mock_pg_sql}):
        create_database(
            {"ENGINE": "django.db.backends.postgresql", "NAME": "mydb", "HOST": "localhost"}
        )
    mock_pg.connect.assert_called_once()
    mock_pg.connect.return_value.cursor.assert_called()


def test_create_database_postgres_import_error() -> None:
    import sys

    with (
        patch.dict(sys.modules, {"psycopg2": None}),
        pytest.raises(RuntimeError, match="psycopg2 is required"),
    ):
        create_database({"ENGINE": "django.db.backends.postgresql", "NAME": "mydb"})


def test_create_database_postgis_calls_create() -> None:
    import sys

    mock_pg = _mock_psycopg2()
    mock_pg_sql = MagicMock()
    with patch.dict(sys.modules, {"psycopg2": mock_pg, "psycopg2.sql": mock_pg_sql}):
        create_database({"ENGINE": "django.contrib.gis.db.backends.postgis", "NAME": "gisdb"})
    mock_pg.connect.assert_called_once()


# ---------------------------------------------------------------------------
# create_database — MySQL path (mocked)
# ---------------------------------------------------------------------------


def _mock_mysqldb() -> MagicMock:
    mock = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    mock.connect.return_value = mock_conn
    return mock


def test_create_database_mysql_calls_create() -> None:
    import sys

    mock_my = _mock_mysqldb()
    cfg = {"ENGINE": "django.db.backends.mysql", "NAME": "mydb", "HOST": "localhost", "PORT": 3306}
    with patch.dict(sys.modules, {"MySQLdb": mock_my}):
        create_database(cfg)
    mock_my.connect.assert_called_once()
    mock_my.connect.return_value.cursor.assert_called()
    mock_my.connect.return_value.commit.assert_called_once()


def test_create_database_mysql_import_error() -> None:
    import sys

    with (
        patch.dict(sys.modules, {"MySQLdb": None}),
        pytest.raises(RuntimeError, match="mysqlclient is required"),
    ):
        create_database({"ENGINE": "django.db.backends.mysql", "NAME": "mydb"})


# ---------------------------------------------------------------------------
# create_database — unsupported engine
# ---------------------------------------------------------------------------


def test_create_database_unsupported_engine() -> None:
    with pytest.raises(RuntimeError, match="Unsupported engine for CREATE DATABASE"):
        create_database({"ENGINE": "django.db.backends.oracle", "NAME": "mydb"})


# ---------------------------------------------------------------------------
# drop_database — Postgres path (mocked)
# ---------------------------------------------------------------------------


def test_drop_database_postgres_calls_drop() -> None:
    import sys

    mock_pg = _mock_psycopg2()
    mock_pg_sql = MagicMock()
    with patch.dict(sys.modules, {"psycopg2": mock_pg, "psycopg2.sql": mock_pg_sql}):
        drop_database(
            {"ENGINE": "django.db.backends.postgresql", "NAME": "mydb", "HOST": "localhost"}
        )
    mock_pg.connect.assert_called_once()
    # Two execute calls: pg_terminate_backend + DROP DATABASE
    cursor = mock_pg.connect.return_value.cursor.return_value.__enter__.return_value
    assert cursor.execute.call_count == 2


def test_drop_database_postgres_import_error() -> None:
    import sys

    with (
        patch.dict(sys.modules, {"psycopg2": None}),
        pytest.raises(RuntimeError, match="psycopg2 is required"),
    ):
        drop_database({"ENGINE": "django.db.backends.postgresql", "NAME": "mydb"})


# ---------------------------------------------------------------------------
# drop_database — MySQL path (mocked)
# ---------------------------------------------------------------------------


def test_drop_database_mysql_calls_drop() -> None:
    import sys

    mock_my = _mock_mysqldb()
    cfg = {"ENGINE": "django.db.backends.mysql", "NAME": "mydb", "HOST": "localhost", "PORT": 3306}
    with patch.dict(sys.modules, {"MySQLdb": mock_my}):
        drop_database(cfg)
    mock_my.connect.assert_called_once()
    mock_my.connect.return_value.commit.assert_called_once()


def test_drop_database_mysql_import_error() -> None:
    import sys

    with (
        patch.dict(sys.modules, {"MySQLdb": None}),
        pytest.raises(RuntimeError, match="mysqlclient is required"),
    ):
        drop_database({"ENGINE": "django.db.backends.mysql", "NAME": "mydb"})


# ---------------------------------------------------------------------------
# drop_database — unsupported engine
# ---------------------------------------------------------------------------


def test_drop_database_unsupported_engine() -> None:
    with pytest.raises(RuntimeError, match="Unsupported engine for DROP DATABASE"):
        drop_database({"ENGINE": "django.db.backends.oracle", "NAME": "mydb"})


# ---------------------------------------------------------------------------
# find_git_root — no git repo
# ---------------------------------------------------------------------------


def test_find_git_root_returns_none_outside_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tmp_path is in /var/... which is outside any git repo
    no_git = tmp_path / "no_git_here"
    no_git.mkdir()
    monkeypatch.chdir(no_git)
    result = find_git_root()
    assert result is None


# ---------------------------------------------------------------------------
# local_git_branch_names / current_git_branch — git not available
# ---------------------------------------------------------------------------


def test_local_git_branch_names_returns_empty_on_error() -> None:
    with patch("migraid.operations.branch_db.local_git_branch_names", side_effect=Exception):
        pass  # just confirm the function itself handles exceptions
    # Test the real function by simulating git.Repo raising
    import sys

    mock_git = MagicMock()
    mock_git.Repo.side_effect = Exception("no repo")
    with patch.dict(sys.modules, {"git": mock_git}):
        result = local_git_branch_names()
    assert result == set()


def test_current_git_branch_returns_none_on_error() -> None:
    import sys

    mock_git = MagicMock()
    mock_git.Repo.side_effect = Exception("no repo")
    with patch.dict(sys.modules, {"git": mock_git}):
        result = current_git_branch()
    assert result is None
