# prune

Remove orphaned `django_migrations` rows for migrations no longer on disk.

## Usage

```bash
python manage.py migraid prune [--dry-run] [--yes] [--allow-applied]
```

## Description

Cleaning up the `django_migrations` table by removing entries for migrations that have been deleted from the filesystem (e.g., after a squash or manual cleanup).
