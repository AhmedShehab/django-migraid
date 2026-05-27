# Updating the `django_migrations` table (`--update-db`)

When `rebase`, `renumber`, `fix-conflicts`, or `linearize` rename a migration
**that has already been applied**, the file on disk changes but Django's
bookkeeping does not: the `django_migrations` table still records the old stem.
Django then sees the new file as unapplied and the old name as missing — a desync
that breaks `migrate`.

The `--update-db` flag closes that gap. It renames the matching
`django_migrations` rows in lockstep with the files, in one atomic, reversible
operation.

## Usage

```bash
python manage.py migraid rebase --base main --update-db
python manage.py migraid renumber myapp --update-db
python manage.py migraid fix-conflicts --update-db
python manage.py migraid linearize --update-db
```

`--update-db` **implies `--allow-applied`**: because it keeps the table in step,
renaming applied migrations is safe. (Bare `--allow-applied` still renames files
only and will desync the table — `doctor` flags the result as **E005**.)

## Zero data loss

The sync is a raw `UPDATE` of the `name` column only:

```sql
UPDATE django_migrations SET name='0008_foo'
 WHERE app='myapp' AND name='0005_foo';
```

The row id and the original `applied` timestamp are preserved — nothing is
deleted and re-inserted. Several guarantees back this up:

- **Atomic.** The file renames and the row `UPDATE`s run inside a single
  per-app `transaction.atomic()` block. If anything fails — a row-count
  mismatch, a post-apply validation regression, an I/O error — the file changes
  are rolled back *and* the transaction is rolled back. You end up exactly where
  you started.
- **Collision-safe.** If a target name already names a different row, the update
  aborts before touching anything.
- **Self-verifying.** Each `UPDATE` must affect exactly one row, or the whole
  operation rolls back.
- **Reversible.** Before committing, an inverse-SQL script is written to the
  working directory:

  ```
  migraid-syncdb-undo-<app>-<timestamp>.sql
  ```

  Replay it against the same database to restore the previous names.

## Previewing changes

Without `--noinput`, the command prints the target database, a table of every
row it will rename (with the `applied` timestamp it will preserve), and the
literal SQL — then asks for confirmation:

```
Target DB: postgres @ db.prod.internal / appdb
django_migrations changes (1 row(s)):
  myapp  0005_foo -> 0008_foo  (applied 2026-01-02 …, kept)
SQL to run:
  UPDATE django_migrations SET name='0008_foo' WHERE app='myapp' AND name='0005_foo';
Apply these changes? [y/N]
```

`--dry-run` shows the same preview and writes nothing — no files, no rows, no
undo script.

## Pipelines (`--noinput`)

For CI, `--noinput` (alias: `--yes`) skips the confirmation prompt:

```bash
python manage.py migraid rebase --base main --update-db --noinput
```

The target database is still echoed for the audit log. There is no local-host
restriction — updating is a deliberate, opt-in operation meant to run against
real databases — so make sure the job points at the database you intend.

## Choosing the database

`--database ALIAS` selects which connection's `django_migrations` table to update
(default: `default`), mirroring Django's `migrate --database`:

```bash
python manage.py migraid rebase --update-db --database replica --noinput
```

Run the command once per database alias you need to update.

## Recovering from an existing desync

If a migration was already renamed file-only (e.g. `--allow-applied` without
`--update-db`), there is no rename in flight for `--update-db` to attach to.
`doctor` reports it as **E005** with the exact recovery SQL. Either:

1. Revert the file rename in git, then re-run the command with `--update-db`; or
2. Run the `UPDATE` from the `doctor` hint by hand.

## Deprecated alias

`--sync-db` is a deprecated alias for `--update-db`. It still works but prints a
warning. It will be removed in a future release.
