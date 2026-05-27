# renumber

Fix gap or duplicate numbering in a single app's migrations.

## Usage

```bash
python manage.py migraid renumber <app> [--dry-run] [--yes] [--force] [--allow-applied] [--update-db] [--noinput] [--database ALIAS]
```

## Description

Standardizes the numbering of an app's migrations to be sequential (0001, 0002, 0003, ...) without gaps or duplicates, while maintaining the dependency graph.

## Keeping the database in sync

If any renamed migration has already been applied, add `--update-db` to rename the
matching `django_migrations` rows in the same atomic, reversible step (implies
`--allow-applied`). Use `--noinput` for CI and `--database ALIAS` to target a
non-default connection. See [Syncing the `django_migrations` table](../update-db.md).
