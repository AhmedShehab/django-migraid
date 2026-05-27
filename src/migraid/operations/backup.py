"""Git safety guard for mutation commands."""

from __future__ import annotations

import time
from pathlib import Path


class DirtyWorkingTreeError(Exception):
    pass


class NotAGitRepoError(Exception):
    pass


class GitGuard:
    """Wraps a git.Repo to provide safety checks and backup operations."""

    def __init__(self, path: Path | None = None) -> None:
        try:
            import git

            search = str(path) if path else "."
            self._repo = git.Repo(search, search_parent_directories=True)
        except Exception as exc:
            # ImportError (gitpython not installed) or InvalidGitRepositoryError
            raise NotAGitRepoError(str(exc)) from exc

    def assert_clean_working_tree(self, force: bool = False) -> None:
        if force:
            return
        if self._repo.is_dirty(untracked_files=False):
            raise DirtyWorkingTreeError(
                "Working tree has uncommitted changes. "
                "Commit or stash them first, or use --force to skip this check."
            )

    def create_backup_branch(self, prefix: str = "migraid-backup") -> str:
        """Create a lightweight backup ref at HEAD. Returns the branch name."""
        timestamp = int(time.time())
        branch_name = f"{prefix}-{timestamp}"
        self._repo.create_head(branch_name)
        return branch_name

    def delete_backup_branch(self, branch_name: str) -> None:
        try:
            branch = self._repo.heads[branch_name]
            self._repo.delete_head(branch)
        except (IndexError, Exception):
            pass

    def local_migrations_since(
        self,
        base_ref: str,
        app_label: str | None = None,
    ) -> set[str]:
        """Return stems of migration files added on HEAD since diverging from base_ref."""
        try:
            merge_bases = self._repo.merge_base(base_ref, "HEAD")
            if not merge_bases:
                return set()
            base_sha = merge_bases[0].hexsha
        except Exception:
            return set()

        pattern = "*/migrations/*.py"
        if app_label:
            pattern = f"*{app_label}*/migrations/*.py"

        try:
            output: str = self._repo.git.diff(
                base_sha,
                "HEAD",
                "--name-only",
                "--diff-filter=A",
                "--",
                pattern,
            )
        except Exception:
            return set()

        result: set[str] = set()
        for line in output.splitlines():
            p = Path(line)
            if p.suffix == ".py" and not p.name.startswith("__"):
                result.add(p.stem)
        return result

    def untracked_migration_files(self, app_dirs: list[tuple[str, Path]]) -> list[Path]:
        """Return untracked migration .py files (not __init__.py) inside known migrations dirs."""
        migrations_dirs = {mdir for _, mdir in app_dirs}
        working_dir = Path(self._repo.working_dir)
        result: list[Path] = []
        for path_str in self._repo.untracked_files:
            p = working_dir / path_str
            if p.suffix != ".py" or p.name.startswith("__"):
                continue
            for mdir in migrations_dirs:
                try:
                    p.relative_to(mdir)
                    result.append(p)
                    break
                except ValueError:
                    continue
        return sorted(result)

    def tracked_migration_keys(self, app_dirs: list[tuple[str, Path]]) -> set[tuple[str, str]]:
        """Return (app_label, stem) for all migration .py files tracked by git on HEAD."""
        working_dir = Path(self._repo.working_dir)
        result: set[tuple[str, str]] = set()
        for app_label, migrations_dir in app_dirs:
            try:
                rel_dir = migrations_dir.relative_to(working_dir)
            except ValueError:
                continue
            output: str = self._repo.git.ls_files("--", str(rel_dir / "*.py"))
            for line in output.splitlines():
                p = Path(line.strip())
                if p.suffix == ".py" and not p.name.startswith("__"):
                    result.add((app_label, p.stem))
        return result

    def highest_tracked_stem(self, migrations_dir: Path) -> str | None:
        """Return the stem of the highest-numbered migration tracked by git, or None."""
        working_dir = Path(self._repo.working_dir)
        try:
            rel_dir = migrations_dir.relative_to(working_dir)
        except ValueError:
            return None
        output: str = self._repo.git.ls_files("--", str(rel_dir / "*.py"))
        stems = []
        for line in output.splitlines():
            p = Path(line.strip())
            if p.suffix == ".py" and not p.name.startswith("__"):
                stems.append(p.stem)
        return sorted(stems)[-1] if stems else None

    def base_leaf_for_app(self, base_ref: str, app_label: str) -> str | None:
        """Return the migration stem at the tip of base_ref for the given app, if any."""
        try:
            output: str = self._repo.git.show(
                f"{base_ref}:.",
                "--name-only",
            )
        except Exception:
            return None

        # Find migrations belonging to this app
        import re

        pattern = re.compile(rf".*{app_label}.*/migrations/(\d{{4}}_\w+)\.py$")
        stems: list[str] = []
        for line in output.splitlines():
            m = pattern.match(line)
            if m:
                stems.append(m.group(1))
        if stems:
            return sorted(stems)[-1]
        return None
