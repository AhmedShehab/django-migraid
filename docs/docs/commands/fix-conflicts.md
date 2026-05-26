# fix-conflicts

Resolve multiple-leaf conflicts by linearizing the fork.

## Usage

```bash
python manage.py migraid fix-conflicts [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied]
```

## Description

If an app has multiple "leaf" migrations (heads), `fix-conflicts` will linearize them by making one depend on the other, resolving the "multiple leaves" error in Django.
