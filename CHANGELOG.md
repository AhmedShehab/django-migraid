# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0b3] - 2026-05-27

### Fixed
- Broken `../sync-db.md` link in `doctor.md` (renamed to `update-db.md` in 0.2.0b2).

## [0.2.0b2] - 2026-05-27

### Added
- `sync-branch` subcommand: align local migration files (and optionally the DB) to the current git branch state. Detects and deletes untracked migration files; with `--update-db` also removes stale `django_migrations` rows; with `--schema` runs `migrate` backwards for apps whose applied state exceeds the git-tracked state.

### Changed
- **Renamed flag: `--sync-db` → `--update-db`** on `rebase`, `fix-conflicts`, `linearize`, and `renumber`. The old `--sync-db` remains as a deprecated alias (emits a warning) and will be removed in a future release.
- `sync-branch` is now **file-plane by default** — DB rows are only touched with `--update-db`. This enforces the safety model: no DB change without an explicit flag.
- **Standardized flags across all mutation commands:** `--dry-run` (default OFF), `--yes`, `--noinput` (alias of `--yes`), `--database ALIAS`. `prune` now previews and prompts by default instead of requiring `--dry-run`.
- Removed the `--no-input` spelling (kept only `--noinput`, matching Django's convention).
- Docs renamed `sync-db.md` → `update-db.md`; updated all cross-references.

### Breaking Changes
- **`prune --allow-applied` is removed.** Use `prune --allow-remote-db` to allow pruning against a non-local database host. The old flag had a different meaning than `--allow-applied` on all other commands (which means "operate on applied migrations"), causing confusing collision.
- `prune` no longer defaults to dry-run; it now previews and asks for confirmation. Pass `--dry-run` explicitly for preview-only mode, or `--yes` to skip the prompt.

## [0.2.0b1] - 2026-05-27

### Added
- Beta release 0.2.0b1 with improved CI/CD and docs structure.

## [0.1.0b1] - 2024-05-26

### Added
- `linearize` command: rewrite an app's history into a gap-free `0001..N` chain where each migration depends on exactly one predecessor. Renumbers, collapses redundant in-app dependency lists, resolves forks (subsumes `fix-conflicts`), and deletes merge migrations. Preserves cross-app dependencies by default (`--strip-cross-app` to drop them); aborts on merges that carry operations or in-app `run_before`. Supports `--sync-db`, which now also `DELETE`s `django_migrations` rows for removed applied merges (with re-`INSERT` undo SQL).

## [0.1.0b1] - 2024-05-26

### Added
- Beta release with initial feature set.
- All features from 0.1.0-alpha.

## [0.1.0] - 2024-01-01

### Added
- `doctor` command: read-only diagnostic with 11 issue detectors (E001–E004, W001–W005, I001–I002)
- `rebase` command: renumber branch-local migrations onto a target branch
- `fix-conflicts` command: linearize conflicting leaf migrations
- `renumber` command: fix gap/duplicate numbering for an app
- `prune` command: remove stale `django_migrations` rows
- `graph` command: visualize migration DAG in ASCII, Mermaid, or Graphviz dot format
- Static-first analysis (Tier 1) using libcst — works on broken/mid-rebase repos
- Live Django loader integration (Tier 2) for DB-dependent checks
- Safety pipeline: dirty-tree guard, applied-migration guard, backup ref, undo log, post-apply validation
- Apache 2.0 license

[Unreleased]: https://github.com/AhmedShehab/django-migraid/compare/v0.1.0b2...HEAD
[0.1.0b2]: https://github.com/AhmedShehab/django-migraid/compare/v0.1.0b1...v0.1.0b2
[0.1.0b1]: https://github.com/AhmedShehab/django-migraid/releases/tag/v0.1.0b1
[0.1.0]: https://github.com/AhmedShehab/django-migraid/releases/tag/v0.1.0
