# linearize

Rewrite an app's history into a clean, gap-free `0001..N` chain where every
migration depends on exactly one predecessor.

## Usage

```bash
python manage.py migraid linearize [--app LABEL] [--strip-cross-app] [--dry-run] [--yes] [--force] [--allow-applied] [--update-db] [--noinput] [--database ALIAS]
```

## Description

`linearize` is the most aggressive cleanup command. For each app (all apps by
default, or just `--app LABEL`) it:

- **Renumbers** every migration to a sequential `0001, 0002, 0003, …` with no
  gaps and no duplicates.
- **Collapses dependencies** so each migration's only in-app dependency is the
  migration directly before it — removing redundant "double dependency" lists
  like:

  ```python
  dependencies = [
      ("general_calls", "0016_rename_telnyx_call_id"),
      ("general_calls", "0022_generalcall_call_engine_duration_seconds_and_more"),
  ]
  ```

  becomes a single parent.
- **Resolves forks** itself (it subsumes `fix-conflicts`): diverged branches are
  ordered into one line.
- **Deletes merge migrations** — once history is linear, the no-op `…_merge_…`
  joins are removed.

It does **not** squash operations: a project with 15 migrations still has 15
migrations afterwards (minus any merges). Only filenames and dependency lists
change.

## Cross-app dependencies

A dependency that points at *another* app (for example a FK target) is preserved
by default — stripping it would break Django's apply order. Pass
`--strip-cross-app` only if you are certain those edges are unnecessary; it can
make `migrate` fail or build schema in the wrong order.

## What makes it abort

`linearize` refuses to run (with a clear message) when an automatic collapse
would be unsafe:

- a `…_merge_…` migration that actually carries operations (deleting it would
  lose work), or
- an app that uses an **in-app** `run_before` constraint (the linear chain can't
  be trusted to honor it).

Squashed migrations (those with a `replaces` list) are treated as ordinary
nodes: renumbered, with their `replaces` entries rewritten to match.

## Keeping the database in sync

If any renamed or deleted migration has already been applied, add `--update-db` to
update the matching `django_migrations` rows in the same atomic, reversible step
(implies `--allow-applied`). Renames become `UPDATE`s that preserve the original
`applied` timestamp; a removed applied merge becomes a `DELETE` with a matching
re-`INSERT` in the undo script. Use `--noinput` for CI and `--database ALIAS`
to target a non-default connection. See
[Syncing the `django_migrations` table](../update-db.md).
