# renumber

Fix gap or duplicate numbering in a single app's migrations.

## Usage

```bash
python manage.py migraid renumber <app> [--dry-run] [--yes] [--force] [--allow-applied]
```

## Description

Standardizes the numbering of an app's migrations to be sequential (0001, 0002, 0003, ...) without gaps or duplicates, while maintaining the dependency graph.
