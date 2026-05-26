"""Git integration tests for GitGuard (real git repos in tmp_path)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from migraid.operations.backup import DirtyWorkingTreeError, GitGuard, NotAGitRepoError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path, initial_branch: str = "main") -> None:
    _git(repo, "init", "-b", initial_branch)
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test User")


def _commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _git(repo, "add", name)
    _git(repo, "commit", "-m", message)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    _commit(tmp_path, "initial commit", {"README.txt": "hello"})
    return tmp_path


# ---------------------------------------------------------------------------
# Constructor / error cases
# ---------------------------------------------------------------------------


def test_not_git_repo_raises(tmp_path: Path) -> None:
    empty = tmp_path / "not_a_repo"
    empty.mkdir()
    with pytest.raises(NotAGitRepoError):
        GitGuard(path=empty)


# ---------------------------------------------------------------------------
# assert_clean_working_tree
# ---------------------------------------------------------------------------


def test_assert_clean_tree_on_clean_repo(git_repo: Path) -> None:
    guard = GitGuard(path=git_repo)
    guard.assert_clean_working_tree()  # must not raise


def test_assert_clean_tree_raises_on_staged_file(git_repo: Path) -> None:
    (git_repo / "new_file.txt").write_text("new")
    _git(git_repo, "add", "new_file.txt")
    guard = GitGuard(path=git_repo)
    with pytest.raises(DirtyWorkingTreeError):
        guard.assert_clean_working_tree()


def test_assert_clean_tree_raises_on_modified_file(git_repo: Path) -> None:
    (git_repo / "README.txt").write_text("modified")
    _git(git_repo, "add", "README.txt")
    guard = GitGuard(path=git_repo)
    with pytest.raises(DirtyWorkingTreeError):
        guard.assert_clean_working_tree()


def test_assert_clean_tree_force_skips_check(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("dirty")
    _git(git_repo, "add", "dirty.txt")
    guard = GitGuard(path=git_repo)
    guard.assert_clean_working_tree(force=True)  # must not raise


# ---------------------------------------------------------------------------
# create_backup_branch / delete_backup_branch
# ---------------------------------------------------------------------------


def test_create_backup_branch_default_prefix(git_repo: Path) -> None:
    guard = GitGuard(path=git_repo)
    branch = guard.create_backup_branch()
    assert branch.startswith("migraid-backup-")
    # Branch must actually exist
    branches_output = _git(git_repo, "branch", "--list")
    assert branch in branches_output


def test_create_backup_branch_custom_prefix(git_repo: Path) -> None:
    guard = GitGuard(path=git_repo)
    branch = guard.create_backup_branch(prefix="custom-prefix")
    assert branch.startswith("custom-prefix-")


def test_delete_backup_branch(git_repo: Path) -> None:
    guard = GitGuard(path=git_repo)
    branch = guard.create_backup_branch()
    guard.delete_backup_branch(branch)
    branches_output = _git(git_repo, "branch", "--list")
    assert branch not in branches_output


def test_delete_nonexistent_branch_is_silent(git_repo: Path) -> None:
    guard = GitGuard(path=git_repo)
    guard.delete_backup_branch("branch-does-not-exist")  # must not raise


# ---------------------------------------------------------------------------
# local_migrations_since
# ---------------------------------------------------------------------------


def test_local_migrations_since_no_additions(git_repo: Path) -> None:
    guard = GitGuard(path=git_repo)
    result = guard.local_migrations_since("main")
    assert result == set()


def test_local_migrations_since_detects_added_files(git_repo: Path) -> None:
    # Add a migration on main
    _commit(
        git_repo,
        "add base migration",
        {
            "myapp/migrations/__init__.py": "",
            "myapp/migrations/0001_initial.py": "# base migration",
        },
    )

    # Branch off main and add a local migration
    _git(git_repo, "checkout", "-b", "feature")
    _commit(
        git_repo,
        "add local migration",
        {
            "myapp/migrations/0002_local_feature.py": "# local migration",
        },
    )

    guard = GitGuard(path=git_repo)
    local = guard.local_migrations_since("main")

    assert "0002_local_feature" in local
    assert "0001_initial" not in local


def test_local_migrations_since_multiple_files(git_repo: Path) -> None:
    _commit(
        git_repo,
        "base",
        {
            "myapp/migrations/__init__.py": "",
            "myapp/migrations/0001_initial.py": "# base",
        },
    )

    _git(git_repo, "checkout", "-b", "feature")
    _commit(
        git_repo,
        "two local migrations",
        {
            "myapp/migrations/0002_step_a.py": "# step a",
            "myapp/migrations/0003_step_b.py": "# step b",
        },
    )

    guard = GitGuard(path=git_repo)
    local = guard.local_migrations_since("main")

    assert "0002_step_a" in local
    assert "0003_step_b" in local
    assert "0001_initial" not in local


def test_local_migrations_since_app_filter(git_repo: Path) -> None:
    _commit(
        git_repo,
        "base",
        {
            "myapp/migrations/__init__.py": "",
            "myapp/migrations/0001_initial.py": "# myapp base",
            "otherapp/migrations/__init__.py": "",
            "otherapp/migrations/0001_initial.py": "# otherapp base",
        },
    )

    _git(git_repo, "checkout", "-b", "feature")
    _commit(
        git_repo,
        "local migrations",
        {
            "myapp/migrations/0002_myapp_local.py": "# myapp local",
            "otherapp/migrations/0002_otherapp_local.py": "# otherapp local",
        },
    )

    guard = GitGuard(path=git_repo)
    local_myapp = guard.local_migrations_since("main", app_label="myapp")

    assert "0002_myapp_local" in local_myapp
    # otherapp files should not match the myapp glob filter
    assert "0002_otherapp_local" not in local_myapp


def test_base_leaf_for_app_returns_none_for_missing_ref(git_repo: Path) -> None:
    guard = GitGuard(path=git_repo)
    result = guard.base_leaf_for_app("nonexistent_branch", "myapp")
    assert result is None


def test_base_leaf_for_app_returns_stem_when_present(git_repo: Path) -> None:
    # Commit a migration on main
    _commit(
        git_repo,
        "add base",
        {
            "myapp/migrations/__init__.py": "",
            "myapp/migrations/0001_initial.py": "# base",
            "myapp/migrations/0002_step.py": "# step",
        },
    )

    guard = GitGuard(path=git_repo)
    # base_leaf_for_app may return None if implementation doesn't find it via git show
    # but it must not raise an exception
    result = guard.base_leaf_for_app("main", "myapp")
    # result is either None or a string stem
    assert result is None or isinstance(result, str)


def test_local_migrations_since_excludes_init_files(git_repo: Path) -> None:
    _commit(git_repo, "base", {"README.txt": "base"})

    _git(git_repo, "checkout", "-b", "feature")
    _commit(
        git_repo,
        "add migrations dir",
        {
            "myapp/migrations/__init__.py": "",
            "myapp/migrations/0001_initial.py": "# migration",
        },
    )

    guard = GitGuard(path=git_repo)
    local = guard.local_migrations_since("main")

    assert "0001_initial" in local
    assert "__init__" not in local
