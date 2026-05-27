# rebase

Renumber local branch migrations to follow the latest from a target branch.

## Usage

```bash
python manage.py migraid rebase [--base BRANCH] [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied] [--update-db] [--noinput] [--database ALIAS]
```

## Description

The `rebase` command helps linearize your branch's migrations when parallel development causes conflicts or gaps in numbering. It identifies migrations unique to your branch and renumbers them to follow the latest migration on the target base branch (defaulting to `main`).

## Keeping the database in sync

If any renamed migration has already been applied, add `--update-db` to rename the
matching `django_migrations` rows in the same atomic, reversible step (implies
`--allow-applied`). Use `--noinput` for CI and `--database ALIAS` to target a
non-default connection. See [Syncing the `django_migrations` table](../update-db.md).
