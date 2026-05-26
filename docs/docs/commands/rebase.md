# rebase

Renumber local branch migrations to follow the latest from a target branch.

## Usage

```bash
python manage.py migraid rebase [--base BRANCH] [--app LABEL] [--dry-run] [--yes] [--force] [--allow-applied]
```

## Description

The `rebase` command helps linearize your branch's migrations when parallel development causes conflicts or gaps in numbering. It identifies migrations unique to your branch and renumbers them to follow the latest migration on the target base branch (defaulting to `main`).
