# Common Django Migration Errors

This guide helps you diagnose and fix common Django migration errors using `django-migraid`.

## CircularDependencyError

**The Problem:** You have two or more migrations that depend on each other in a cycle (e.g., App A Migration 0002 depends on App B Migration 0001, and App B Migration 0002 depends on App A Migration 0002).

**Search Terms:** `django CircularDependencyError`, `migration depends on itself`, `break circular migration dependency`.

**How to fix:**
1. Run `python manage.py migraid doctor` to identify the specific migrations involved in the cycle (Error **E002**).
2. Use `python manage.py migraid graph` to visualize the cycle.
3. Manually edit the `dependencies` list in one of the migrations to break the cycle.

## InconsistentMigrationHistory

**The Problem:** Django detects that a migration is applied, but one of its dependencies is NOT applied. This often happens after renumbering migrations or rebasing without updating the database.

**Search Terms:** `django InconsistentMigrationHistory`, `migration applied before its dependency`, `django_migrations table out of sync`.

**How to fix:**
Use the `--update-db` flag with `renumber` or `rebase` to keep your database in sync with your files (Error **E005**):
```bash
python manage.py migraid renumber <app> --update-db
```

## Multiple Leaf Nodes (Merge Conflicts)

**The Problem:** Two developers created a new migration (e.g., `0005_...`) on different branches. When merged, the app has two migrations that both claim to be the "latest".

**Search Terms:** `django migration merge conflict`, `multiple leaf nodes in migration graph`, `makemigrations --merge`.

**How to fix:**
Instead of manually creating a merge migration, use `fix-conflicts` (Error **E001**):
```bash
python manage.py migraid fix-conflicts
```

## NodeNotFoundError

**The Problem:** A migration depends on another migration that no longer exists on disk. This usually happens after a bad rebase or if a migration file was accidentally deleted.

**Search Terms:** `django NodeNotFoundError`, `migration depends on missing node`.

**How to fix:**
Run `python manage.py migraid doctor` to find which migration has the broken dependency (Error **E004**).

## Gaps in Migration Numbering

**The Problem:** Your migrations are numbered `0001`, `0002`, `0005`. While Django handles this, it can lead to confusion and is often a sign of a messy rebase.

**Search Terms:** `django migration gap numbering`, `renumber django migrations`.

**How to fix:**
Use `renumber` to close the gaps (Warning **W006**):
```bash
python manage.py migraid renumber <app>
```

## Stale entries in `django_migrations`

**The Problem:** Your `django_migrations` table contains rows for migrations that are no longer in your codebase.

**Search Terms:** `remove deleted migrations from django_migrations`, `ghost migrations django`.

**How to fix:**
Use `prune` to safely remove these entries (Warning **W001**):
```bash
python manage.py migraid prune
```
