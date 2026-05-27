# sync-branch

Align local migration files (and optionally the database) to the current git branch state.

## Usage

```bash
python manage.py migraid sync-branch [--app LABEL] [--dry-run] [--yes] [--noinput] [--database ALIAS] [--update-db] [--schema]
```

## Description

`sync-branch` is designed for the workflow where you have untracked (uncommitted) migration files that were created on a branch you are leaving. It:

1. **Detects untracked migration files** — any `.py` file in a migrations directory that `git` considers untracked.
2. **(Optional) Deletes stale `django_migrations` rows** — with `--update-db`, removes applied rows for migrations whose files are no longer tracked by git.
3. **(Optional) Reverses schema changes** — with `--schema`, calls `manage.py migrate` backwards for any app where the applied state exceeds the git-tracked state (requires the migration files to still be on disk).

The command is **file-plane by default**. DB writes require an explicit flag.

## Flags

| Flag | Default | Description |
|---|---|---|
| `--app LABEL` | all apps | Limit to one app. |
| `--dry-run` | off | Preview changes without making them. |
| `--yes` / `--noinput` | off | Skip the confirmation prompt. |
| `--database ALIAS` | `default` | Database alias to inspect. |
| `--update-db` | off | Also delete stale `django_migrations` rows for branch-excess applied migrations. |
| `--schema` | off | Also run `migrate` backwards to reverse schema changes (requires files on disk). |

## git is required

`sync-branch` always requires a git repository. It uses `git ls-files` and `git status` to distinguish tracked from untracked files. There is no `--force` bypass.

## Typical workflow

```bash
# You are on feature-branch with untracked migration files that were applied locally.
# You want to switch to main without carrying those files.

# 1. Preview what sync-branch would do
python manage.py migraid sync-branch --dry-run

# 2. Delete the untracked files only (default — no DB changes)
python manage.py migraid sync-branch --yes

# 3. Or: also remove the applied rows from django_migrations
python manage.py migraid sync-branch --update-db --yes

# 4. Or: full cleanup — reverse schema changes too (files must still be on disk)
python manage.py migraid sync-branch --schema --yes
```

## `sync-branch` vs `prune`

| Situation | Use |
|---|---|
| Untracked/uncommitted migration files left over from a branch | `sync-branch` |
| Migration files deleted from the repo (squash, manual cleanup) | `prune` |
