# Known Migration Issues

This document catalogs the migration problems django-migraid detects and (where safe) auto-fixes.

## E001 — Conflicting Leaf Migrations

**Symptoms:** `CommandError: Conflicting migrations detected` when running `migrate` or `makemigrations`.

**Root cause:** Two developers each created a migration from the same parent on separate branches. When the branches are combined, the migration DAG has two "leaf" (head) nodes in one app.

**Manual fix:** `python manage.py makemigrations --merge`

**Auto-fix:** `python manage.py migraid fix-conflicts` — linearizes the fork by renumbering the second leaf to follow the first.

---

## E002 — Circular Migration Dependencies

**Symptoms:** `CircularDependencyError` during `migrate` or `squashmigrations`.

**Root cause:** App A depends on a migration in App B, and App B depends on a migration in App A.

**Manual fix:** Break the cycle by splitting one of the foreign keys into a separate migration, or restructuring cross-app dependencies.

**Auto-fix:** Not possible automatically — requires domain knowledge of which dependency to break.

---

## E003 — Out-of-Order / Gap Numbering

**Symptoms:** Migration files numbered `0001`, `0003` (skipping `0002`), or two files with the same prefix after a rebase.

**Root cause:** After a `git rebase`, local migrations may have numbering that conflicts with or creates gaps relative to the target branch.

**Manual fix:** Rename migration files and update their `dependencies` lists.

**Auto-fix:** `python manage.py migraid renumber <app>`

---

## E004 — Dependency on a Deleted Migration

**Symptoms:** `NodeNotFoundError` during `migrate`, or silent missing-migration errors.

**Root cause:** A migration's `dependencies` list references `("app", "name")` where that migration file no longer exists on disk — typically from an incomplete squash transition or a cherry-pick that missed a file.

**Manual fix:** Update the dangling `dependencies` entry to point to the squash migration or the correct replacement.

**Auto-fix:** Not possible automatically — the correct replacement must be determined by the developer.

---

## E005 — Renamed Applied Migration (Table Desync)

**Symptoms:** `migrate` reports a migration as unapplied even though its schema changes are already in the database, and an old migration name appears "missing." `doctor` shows a `django_migrations` row whose name has no file on disk while a same-suffix file exists.

**Root cause:** An applied migration was renamed on disk (e.g. `rebase`/`renumber`/`fix-conflicts` with `--allow-applied`, or a manual rename) without updating the `django_migrations` table, so the recorded name no longer matches the file.

**Manual fix:** `UPDATE django_migrations SET name='<new>' WHERE app='<app>' AND name='<old>';` (the exact statement is in the `doctor` hint), or revert the file rename in git.

**Auto-fix:** Re-run the rename command with [`--sync-db`](sync-db.md), which renames the file and the row together. Going forward, always pass `--sync-db` instead of `--allow-applied` when renaming applied migrations.

---

## W001 — Stale `django_migrations` Rows

**Symptoms:** `django_migrations` table contains rows for migrations that no longer exist on disk. Subsequent migrations may fail or produce confusing output.

**Root cause:** Migration files were deleted or renamed without updating the database, or a branch was switched without rolling back first.

**Manual fix:** Manually delete the orphaned rows from `django_migrations`.

**Auto-fix:** `python manage.py migraid prune` (dry-run by default, requires `--yes` to execute).

---

## W002 — `RunPython` / `RunSQL` Without Reverse Code

**Symptoms:** `migrate --plan` shows `IRREVERSIBLE`. Rolling back fails with an error.

**Root cause:** A `RunPython` operation was created without a `reverse_code` parameter (defaults to `None`). A `RunSQL` operation was created without `reverse_sql`.

**Manual fix:** Add `reverse_code=migrations.RunPython.noop` (to explicitly mark as irreversible) or a real reverse function. Add `reverse_sql=migrations.RunSQL.noop` for SQL operations.

**Auto-fix:** Not possible — requires domain knowledge of the correct reverse logic.

---

## W003 — Incomplete Squash Transition

**Symptoms:** Both the squashed migration (with `replaces=[...]`) and the original migration files it replaces are still present on disk.

**Root cause:** Django's squashing process requires a manual transition step: after all environments have applied the squash migration, delete the originals and remove the `replaces` attribute. This is often forgotten.

**Manual fix:** Delete all migration files listed in the squash's `replaces=[...]` list, update any migrations that depended on them to depend on the squash migration instead, then remove the `replaces` attribute.

**Auto-fix:** Not currently automated — too risky without verifying all environments have applied the squash.

---

## W004 — Merge Migrations in a Rebase-Workflow Repo

**Symptoms:** Merge migrations (created by `makemigrations --merge`) exist in a repository that uses `git rebase` rather than `git merge`. Execution order becomes non-deterministic.

**Root cause:** `makemigrations --merge` creates a migration that depends on two parents. In a rebase workflow this creates an inconsistency — the "merge" is semantically wrong.

**Manual fix:** Delete the merge migration and rebase/renumber the conflicting migrations instead.

**Auto-fix:** `python manage.py migraid rebase`

---

## W005 — Non-Deterministic Dependency Ordering

**Symptoms:** Migration files show unnecessary diffs between developers or CI runs because `dependencies` list order varies.

**Root cause:** Django's `makemigrations` uses sets internally, and before Python 3.7+ hash-seed stabilization, dependency list order could vary between runs.

**Manual fix:** Alphabetically sort the `dependencies` list in affected migration files.

**Auto-fix:** Not currently automated. Use the `doctor` output to identify affected files.

---

## I001 — Cross-App Dependency Risks

**Symptoms:** Migrations in multiple apps depend on each other in complex ways, making ordering fragile.

**Root cause:** ForeignKey relationships between apps create implicit migration dependencies that can become tangled during parallel development.

**Manual fix:** Review the dependency graph (`migraid graph`) and ensure cross-app dependencies are as minimal as possible.

---

## I002 — `--fake` / `--fake-initial` Footgun Patterns

**Symptoms:** `django_migrations` table says a migration is applied but the actual database schema doesn't match.

**Root cause:** `--fake` was used to mark migrations as applied without actually running them. `--fake-initial` has similar risks on non-initial migrations.

**Manual fix:** Carefully diff the current schema against the expected schema, then apply missing DDL manually or re-run the affected migrations.
