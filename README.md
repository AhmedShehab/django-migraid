# django-migraid

**Detect, diagnose, and auto-fix Django migration problems in Git workflows.**

[![CI](https://github.com/AhmedShehab/django-migraid/actions/workflows/ci.yml/badge.svg)](https://github.com/AhmedShehab/django-migraid/actions)
[![PyPI](https://img.shields.io/pypi/v/django-migraid.svg)](https://pypi.org/project/django-migraid/)
[![Python](https://img.shields.io/pypi/pyversions/django-migraid.svg)](https://pypi.org/project/django-migraid/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

---

## The Problem

Two developers branch from `main` at migration `0004`. Both generate `0005_*.py`. Main merges one. The second developer's rebase leaves them with a conflict that `makemigrations --merge` doesn't cleanly handle in rebase-based workflows. django-migraid fixes this — and ten other common migration pain points.

## Installation

```bash
pip install django-migraid
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...
    "migraid",
]
```

## Quick Start

```bash
# Diagnose all migration issues in your project
python manage.py migraid doctor

# Rebase your branch's migrations onto main
python manage.py migraid rebase --base main --dry-run

# Fix conflicting leaf migrations
python manage.py migraid fix-conflicts --dry-run

# Fix out-of-order numbering
python manage.py migraid renumber myapp --dry-run

# Remove stale django_migrations rows
python manage.py migraid prune

# Visualize the migration DAG
python manage.py migraid graph myapp --format mermaid
```

## Problems This Solves

| Issue | Code | Command |
|-------|------|---------|
| Conflicting leaf migrations (parallel development) | E001 | `fix-conflicts` |
| Circular migration dependencies | E002 | — (reports) |
| Out-of-order / gap numbering after rebase | E003 | `renumber` |
| Dependency on a deleted migration | E004 | — (reports) |
| Stale `django_migrations` rows | W001 | `prune` |
| `RunPython` without `reverse_code` | W002 | — (reports) |
| Squashed migration with old files still present | W003 | — (reports) |
| Merge migrations in a rebase-workflow repo | W004 | `rebase` |
| Non-deterministic dependency ordering | W005 | — (reports) |
| Cross-app dependency risks | I001 | — (reports) |
| `--fake` / `--fake-initial` footgun patterns | I002 | — (reports) |

## Command Reference

### `doctor`

Read-only diagnostic. Reports every detected issue with severity.

```bash
python manage.py migraid doctor [--app LABEL] [--format text|json]
```

### `rebase`

Renumber local branch migrations to follow the latest from a target branch.

```bash
python manage.py migraid rebase [--base BRANCH] [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied]
```

### `fix-conflicts`

Resolve multiple-leaf conflicts by linearizing the fork.

```bash
python manage.py migraid fix-conflicts [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied]
```

### `renumber`

Fix gap or duplicate numbering in a single app's migrations.

```bash
python manage.py migraid renumber <app> [--dry-run] [--yes] [--force] [--allow-applied]
```

### `prune`

Remove orphaned `django_migrations` rows for migrations no longer on disk.

```bash
python manage.py migraid prune [--dry-run] [--yes] [--allow-applied]
```

### `graph`

Print or export the migration DAG.

```bash
python manage.py migraid graph [app] [--format mermaid|dot|ascii] [--output FILE]
```

## Safety Model

Every mutation command:
1. Checks for uncommitted git changes (bypass with `--force`)
2. Guards against rewriting already-applied migrations (bypass with `--allow-applied`)
3. Creates a `migraid-backup-<timestamp>` git ref before any writes
4. Shows a diff-style preview before making changes
5. Asks for confirmation (bypass with `--yes`)
6. Maintains an undo log — reverses all file ops automatically if anything fails
7. Self-validates after apply: if the migration graph gets worse, auto-reverts

`--dry-run` on any mutation command prints the full preview without writing.

## CI Integration

Add to your pre-push hook or CI pipeline:

```bash
python manage.py migraid doctor --format json | jq '.[] | select(.severity == "error")'
```

Or fail CI on any ERROR-level issue:

```bash
python manage.py migraid doctor
```

(exits non-zero if any E0xx issues are found)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
