# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
