# repair

Fix `InconsistentMigrationHistory` errors in your database.

If you have applied a migration that is now "before" its dependency (usually after a rebase or manual file manipulation), Django's standard `migrate` command will fail with an `InconsistentMigrationHistory` error.

```bash
python manage.py migraid repair [--dry-run] [--yes] [--database ALIAS]
```

## Options

- `--dry-run`: Preview the inconsistency without making changes.
- `--yes`: Skip the confirmation prompt.
- `--database`: The database alias to repair. Defaults to `default`.

## How it works

The `repair` command:
1. Scans for `InconsistentMigrationHistory` errors.
2. Identifies the "misapplied" migration (the one applied before its dependency).
3. Marks that migration as **unapplied** in the `django_migrations` table.
4. Prompts you to run `python manage.py migrate` to re-apply it (and its dependencies) in the correct order.
