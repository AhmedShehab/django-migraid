# doctor

Read-only diagnostic. Reports every detected issue with severity.

## Usage

```bash
python manage.py migraid doctor [--app LABEL] [--format text|json]
```

## Description

The `doctor` command scans your project's migrations for common issues, circular dependencies, and inconsistencies. It provides a detailed report with severity levels (ERROR, WARNING, INFO).

- **Tier 1 (Static)**: Scans files using `libcst` without importing them. Works even if the code is broken.
- **Tier 2 (Live)**: Optional integration with Django's migration loader for database-dependent checks.
