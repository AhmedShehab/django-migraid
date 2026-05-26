# fix-conflicts

Resolve multiple-leaf conflicts by linearizing the fork.

## Usage

```bash
python manage.py migraid fix-conflicts [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied] [--sync-db] [--no-input] [--database ALIAS]
```

## Description

If an app has multiple "leaf" migrations (heads), `fix-conflicts` will linearize them by making one depend on the other, resolving the "multiple leaves" error in Django.

## Keeping the database in sync

If any renamed migration has already been applied, add `--sync-db` to rename the
matching `django_migrations` rows in the same atomic, reversible step (implies
`--allow-applied`). Use `--no-input` for CI and `--database ALIAS` to target a
non-default connection. See [Syncing the `django_migrations` table](../sync-db.md).
