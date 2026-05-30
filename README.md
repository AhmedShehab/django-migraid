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

There are two ways to use it — pick whichever you prefer:

**1. Standalone CLI (zero config).** After installing, the `migraid` command is
available directly. It bootstraps Django for you, so there is **nothing to add
to `INSTALLED_APPS`**:

```bash
migraid doctor
```

It locates your Django settings automatically via (in order): a `--settings
<module>` flag, the `DJANGO_SETTINGS_MODULE` environment variable, or your
project's `manage.py`. Run it from your project directory, or set
`DJANGO_SETTINGS_MODULE` / pass `--settings`.

**2. As a Django app.** Add it to `INSTALLED_APPS` and use it through
`manage.py`:

```python
INSTALLED_APPS = [
    ...
    "migraid",
]
```

Both forms support the exact same subcommands.

## Quick Start

```bash
# Diagnose all migration issues in your project (standalone CLI)
migraid doctor

# ...or via manage.py when installed as an app
python manage.py migraid doctor

# Rebase your branch's migrations onto main
python manage.py migraid rebase --base main --dry-run

# Rebase AND keep django_migrations in sync for applied migrations (CI-friendly)
python manage.py migraid rebase --base main --update-db --noinput

# Fix conflicting leaf migrations
python manage.py migraid fix-conflicts --dry-run

# Fix out-of-order numbering
python manage.py migraid renumber myapp --dry-run

# Remove stale django_migrations rows
python manage.py migraid prune --yes

# Clean up untracked migration files after switching branches
python manage.py migraid sync-branch --dry-run

# Fix InconsistentMigrationHistory in the database
python manage.py migraid repair

# Provision a new database for the current branch
python manage.py migraid db add

# Visualize the migration DAG
python manage.py migraid graph myapp --format mermaid
```

## Problems This Solves

| Issue | Code | Django Error / Search Term | Command |
|-------|------|-----------------------------|---------|
| Conflicting leaf migrations | E001 | `multiple leaf nodes`, `migration merge conflict` | `fix-conflicts` |
| Circular migration dependencies | E002 | `CircularDependencyError`, `circular dependency` | — (reports) |
| Out-of-order numbering | W006 | `gap in numbering`, `renumber migrations` | `renumber` |
| Dependency on a deleted migration | E004 | `NodeNotFoundError`, `missing dependency` | — (reports) |
| Renamed applied migration | E005 | `InconsistentMigrationHistory`, `table desync` | `repair` / `rebase` / `renumber` / `fix-conflicts --update-db` |
| Stale `django_migrations` rows | W001 | `ghost migrations`, `remove from django_migrations` | `prune` |
| `RunPython` without `reverse_code` | W002 | `unreversible data migration` | — (reports) |
| Squashed migration cleanup | W003 | `remove old migrations after squash` | — (reports) |
| Merge migrations in rebase flow | W004 | `delete django merge migrations` | `rebase` |
| Non-deterministic dependencies | W005 | `random migration order` | — (reports) |
| Multi-branch database drift | — | `database state out of sync with branch` | `db add` |

## Common Scenarios & How-To

### How to fix a Django migration merge conflict?
When two developers create `0005_*.py` on different branches, run:
```bash
python manage.py migraid fix-conflicts
```
This linearizes the migrations into `0005_...` and `0006_...` automatically.

### How to rebase migrations onto another branch?
To renumber your local migrations to follow the latest from `main`:
```bash
python manage.py migraid rebase --base main
```

### How to fix `InconsistentMigrationHistory`?
If you've renamed or renumbered migrations that are already applied, use:
```bash
python manage.py migraid repair
```
Or use the `--update-db` flag during renumbering:
```bash
python manage.py migraid renumber myapp --update-db
```
This synchronizes the `django_migrations` table with your new file names.

### How to use a separate database per git branch?
To automatically switch databases when you switch branches:
```bash
python manage.py migraid db add
```
This provisions a new database and registers it to your current branch.

### How to find circular dependencies?
Run the diagnostic tool to identify cycles in your migration graph:
```bash
python manage.py migraid doctor
```

## Command Reference

Commands fall into three groups:

**Diagnose (read-only):** `doctor`, `graph`

**Rewrite migration files:** `rebase`, `fix-conflicts`, `linearize`, `renumber` — file plane only by default; pass `--update-db` to also rename `django_migrations` rows.

**Repair DB / branch state:** `prune`, `sync-branch`, `repair`, `db` — these commands exist to fix or manage the database or branch state directly.

### `doctor`

Read-only diagnostic. Reports every detected issue with severity.

```bash
python manage.py migraid doctor [--app LABEL] [--format text|json]
```

### `rebase`

Renumber local branch migrations to follow the latest from a target branch.

```bash
python manage.py migraid rebase [--base BRANCH] [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied] [--update-db] [--noinput] [--database ALIAS]
```

### `fix-conflicts`

Resolve multiple-leaf conflicts by linearizing the fork.

```bash
python manage.py migraid fix-conflicts [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied] [--update-db] [--noinput] [--database ALIAS]
```

### `linearize`

Rewrite history into a gap-free `0001..N` chain where each migration depends on exactly one predecessor — renumbering, collapsing redundant dependency lists, resolving forks, and deleting merge migrations in one pass. Cross-app dependencies are preserved by default (`--strip-cross-app` to drop them).

```bash
python manage.py migraid linearize [--app LABEL] [--strip-cross-app] [--dry-run] [--yes] [--force] [--allow-applied] [--update-db] [--noinput] [--database ALIAS]
```

### `renumber`

Fix gap or duplicate numbering in a single app's migrations.

```bash
python manage.py migraid renumber <app> [--dry-run] [--yes] [--force] [--allow-applied] [--update-db] [--noinput] [--database ALIAS]
```

### `prune`

Remove orphaned `django_migrations` rows for migrations no longer on disk.

```bash
python manage.py migraid prune [--dry-run] [--yes] [--noinput] [--database ALIAS] [--allow-remote-db]
```

### `sync-branch`

Align local migration files (and optionally the database) to the current git branch state. Detects untracked migration files and optionally removes stale `django_migrations` rows or reverses applied schema changes.

```bash
python manage.py migraid sync-branch [--app LABEL] [--dry-run] [--yes] [--noinput] [--database ALIAS] [--update-db] [--schema]
```

### `graph`

Print or export the migration DAG.

```bash
python manage.py migraid graph [app] [--format mermaid|dot|ascii] [--output FILE]
```

### `repair`

Fix `InconsistentMigrationHistory` by marking misapplied migrations as unapplied so they can be re-run in order.

```bash
python manage.py migraid repair [--dry-run] [--yes] [--database ALIAS]
```

### `db`

Manage per-branch databases. Subcommands: `add`, `rm`, `ls`, `prune`.

```bash
# Provision/register DB for current branch
python manage.py migraid db add [--alias ALIAS] [--database BASE_ALIAS]

# List all mappings
python manage.py migraid db ls

# Remove mapping and drop DB
python manage.py migraid db rm [--branch BRANCH]

# Prune entries for deleted branches
python manage.py migraid db prune
```

## Safety Model

**Commands act on the file plane by default. Any DB change requires an explicit flag.**

- `--update-db` authorizes renaming `django_migrations` rows in step with file renames (rewrite commands) or deleting stale rows (sync-branch).
- `--schema` authorizes running `migrate` backwards to reverse schema changes (sync-branch only).
- `prune` and `sync-branch` are inherently DB/file-repair commands — running them is the authorization, and they always preview + confirm before writing.

Every mutation command also:
1. Checks for uncommitted git changes (bypass with `--force` on rewrite commands)
2. Guards against rewriting already-applied migrations (bypass with `--allow-applied`, or use `--update-db` which implies it)
3. Creates a `migraid-backup-<timestamp>` git ref before any writes
4. Shows a diff-style preview before making changes
5. Asks for confirmation (bypass with `--yes` / `--noinput`)
6. Maintains an undo log — reverses all file ops automatically if anything fails
7. Self-validates after apply: if the migration graph gets worse, auto-reverts

`--dry-run` on any mutation command prints the full preview without writing.

When renaming **applied** migrations, `--update-db` renames the matching
`django_migrations` rows in the same per-app `transaction.atomic()` block as the
file changes (preserving the `applied` timestamp), writes a replayable
inverse-SQL undo script, and rolls back *both* files and rows on any failure.
See the [--update-db guide](https://AhmedShehab.github.io/django-migraid/update-db/).

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
