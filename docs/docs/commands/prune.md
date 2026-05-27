# prune

Remove orphaned `django_migrations` rows for migrations no longer on disk.

## Usage

```bash
python manage.py migraid prune [--dry-run] [--yes] [--noinput] [--database ALIAS] [--allow-remote-db]
```

## Description

Cleans up the `django_migrations` table by removing rows for migrations that have been deleted from the filesystem (e.g., after a squash or manual cleanup). This is the counterpart to `sync-branch --update-db`, which cleans up rows for branch-excess applied migrations after a checkout.

## Flags

| Flag | Default | Description |
|---|---|---|
| `--dry-run` | off | Preview stale rows without deleting them. |
| `--yes` / `--noinput` | off | Skip the confirmation prompt (CI-friendly). |
| `--database ALIAS` | `default` | Database alias to inspect and prune. |
| `--allow-remote-db` | off | Allow pruning against a non-local database host. |

## Safety

By default `prune` refuses to run against a non-local database host (anything other than `localhost`, `127.0.0.1`, or SQLite). Pass `--allow-remote-db` to override.

Running `prune` without `--dry-run` shows the stale rows and asks for confirmation before deleting anything.

## `prune` vs `sync-branch --update-db`

| Situation | Use |
|---|---|
| Migration files deleted from the repo (squash cleanup, manual delete) | `prune` |
| Checked out a different branch; DB has applied rows for branch-local migrations no longer on disk | `sync-branch --update-db` |
