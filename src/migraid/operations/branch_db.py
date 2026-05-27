"""Database-per-branch lifecycle management."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BranchDBEntry:
    alias: str
    db_config: dict[str, Any] | None  # None if alias already exists in Django settings


@dataclass
class BranchDBConfig:
    config_path: Path
    branch_dbs: dict[str, BranchDBEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, repo_root: Path) -> "BranchDBConfig":
        config_path = repo_root / ".migraid" / "config.json"
        if not config_path.exists():
            return cls(config_path=config_path)
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls(config_path=config_path)
        branch_dbs: dict[str, BranchDBEntry] = {}
        for branch, entry_data in data.get("branch_dbs", {}).items():
            branch_dbs[branch] = BranchDBEntry(
                alias=entry_data["alias"],
                db_config=entry_data.get("db_config"),
            )
        return cls(config_path=config_path, branch_dbs=branch_dbs)

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "branch_dbs": {
                branch: {"alias": entry.alias, "db_config": entry.db_config}
                for branch, entry in self.branch_dbs.items()
            }
        }
        self.config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register(self, branch: str, entry: BranchDBEntry) -> None:
        self.branch_dbs[branch] = entry

    def unregister(self, branch: str) -> None:
        self.branch_dbs.pop(branch, None)

    def get_entry(self, branch: str) -> BranchDBEntry | None:
        return self.branch_dbs.get(branch)

    def stale_branches(self, local_branch_names: set[str]) -> list[str]:
        """Return registered branches that no longer exist locally in git."""
        return sorted(b for b in self.branch_dbs if b not in local_branch_names)

    def inject_all(self) -> None:
        """Push stored db_configs into django.db.connections.databases."""
        from django.db import connections

        for entry in self.branch_dbs.values():
            if entry.db_config is not None and entry.alias not in connections.databases:
                connections.databases[entry.alias] = _fill_db_defaults(entry.db_config)


_DB_REQUIRED_DEFAULTS: dict[str, Any] = {
    "ATOMIC_REQUESTS": False,
    "AUTOCOMMIT": True,
    "ENGINE": "django.db.backends.dummy",
    "CONN_MAX_AGE": 0,
    "CONN_HEALTH_CHECKS": False,
    "OPTIONS": {},
    "TIME_ZONE": None,
    "NAME": "",
    "USER": "",
    "PASSWORD": "",
    "HOST": "",
    "PORT": "",
}


def _fill_db_defaults(config: dict[str, Any]) -> dict[str, Any]:
    """Ensure all keys Django expects on a DATABASES entry are present."""
    result = dict(config)
    for key, default in _DB_REQUIRED_DEFAULTS.items():
        result.setdefault(key, default)
    return result


def slugify_branch(branch_name: str) -> str:
    """Convert a git branch name to a safe DB alias (max 50 chars)."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", branch_name).strip("_").lower()
    return (slug or "branch")[:50]


def derive_new_db_config(base_config: dict[str, Any], alias: str) -> dict[str, Any]:
    """Clone base_config and derive a new database NAME for the given alias."""
    config = dict(base_config)
    engine = config.get("ENGINE", "")
    if "sqlite" in engine:
        base_name = str(config.get("NAME") or "db.sqlite3")
        if base_name == ":memory:":
            # Place file-based DB alongside the working directory
            new_name = str(Path.cwd() / f"db_{alias}.sqlite3")
        else:
            p = Path(base_name)
            new_name = str(p.parent / f"{p.stem}_{alias}{p.suffix or '.sqlite3'}")
        config["NAME"] = new_name
    else:
        base_db_name = str(config.get("NAME") or "db")
        config["NAME"] = f"{base_db_name}_{alias}"
    return config


def create_database(db_config: dict[str, Any]) -> None:
    """Create the physical database for non-SQLite engines.

    SQLite files are created automatically by Django's migrate command.
    """
    engine = db_config.get("ENGINE", "")
    if "sqlite" in engine:
        return

    db_name = db_config["NAME"]

    if "postgresql" in engine or "postgis" in engine:
        try:
            import psycopg2
            from psycopg2 import sql as pg_sql
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 is required for Postgres CREATE DATABASE. "
                "Install it with: pip install psycopg2-binary"
            ) from exc
        admin_config = {**db_config, "NAME": "postgres"}
        pg_conn = psycopg2.connect(_build_postgres_dsn(admin_config))
        pg_conn.autocommit = True
        try:
            with pg_conn.cursor() as cur:
                cur.execute(pg_sql.SQL("CREATE DATABASE {}").format(pg_sql.Identifier(db_name)))
        finally:
            pg_conn.close()

    elif "mysql" in engine:
        try:
            import MySQLdb
        except ImportError as exc:
            raise RuntimeError(
                "mysqlclient is required for MySQL CREATE DATABASE. "
                "Install it with: pip install mysqlclient"
            ) from exc
        my_conn = MySQLdb.connect(
            host=db_config.get("HOST", "localhost"),
            port=int(db_config.get("PORT") or 3306),
            user=db_config.get("USER", ""),
            passwd=db_config.get("PASSWORD", ""),
        )
        try:
            with my_conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE `{db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            my_conn.commit()
        finally:
            my_conn.close()

    else:
        raise RuntimeError(f"Unsupported engine for CREATE DATABASE: {engine}")


def drop_database(db_config: dict[str, Any]) -> None:
    """Destroy the physical database."""
    engine = db_config.get("ENGINE", "")
    name = str(db_config.get("NAME") or "")

    if "sqlite" in engine:
        if name and name != ":memory:":
            Path(name).unlink(missing_ok=True)
        return

    if "postgresql" in engine or "postgis" in engine:
        try:
            import psycopg2
            from psycopg2 import sql as pg_sql
        except ImportError as exc:
            raise RuntimeError("psycopg2 is required for Postgres DROP DATABASE") from exc
        admin_config = {**db_config, "NAME": "postgres"}
        pg_conn = psycopg2.connect(_build_postgres_dsn(admin_config))
        pg_conn.autocommit = True
        try:
            with pg_conn.cursor() as cur:
                cur.execute(
                    pg_sql.SQL(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()"
                    ),
                    [name],
                )
                cur.execute(
                    pg_sql.SQL("DROP DATABASE IF EXISTS {}").format(pg_sql.Identifier(name))
                )
        finally:
            pg_conn.close()
        return

    if "mysql" in engine:
        try:
            import MySQLdb
        except ImportError as exc:
            raise RuntimeError("mysqlclient is required for MySQL DROP DATABASE") from exc
        my_conn = MySQLdb.connect(
            host=db_config.get("HOST", "localhost"),
            port=int(db_config.get("PORT") or 3306),
            user=db_config.get("USER", ""),
            passwd=db_config.get("PASSWORD", ""),
        )
        try:
            with my_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
            my_conn.commit()
        finally:
            my_conn.close()
        return

    raise RuntimeError(f"Unsupported engine for DROP DATABASE: {engine}")


def _build_postgres_dsn(config: dict[str, Any]) -> str:
    parts = []
    if config.get("HOST"):
        parts.append(f"host={config['HOST']}")
    if config.get("PORT"):
        parts.append(f"port={config['PORT']}")
    if config.get("USER"):
        parts.append(f"user={config['USER']}")
    if config.get("PASSWORD"):
        parts.append(f"password={config['PASSWORD']}")
    if config.get("NAME"):
        parts.append(f"dbname={config['NAME']}")
    return " ".join(parts)


def find_git_root() -> Path | None:
    """Walk upward from CWD to find the git root directory."""
    current = Path.cwd()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def local_git_branch_names() -> set[str]:
    """Return names of all local git branches."""
    try:
        import git

        repo = git.Repo(".", search_parent_directories=True)
        return {head.name for head in repo.heads}
    except Exception:
        return set()


def current_git_branch() -> str | None:
    """Return the current git branch name, or None if detached/not a git repo."""
    try:
        import git

        repo = git.Repo(".", search_parent_directories=True)
        return repo.active_branch.name
    except Exception:
        return None
