# db

Manage per-branch databases for your Django project.

`django-migraid` can provision and track separate databases for each git branch, allowing you to switch branches without your database state getting out of sync with your migration files.

## Subcommands

### add

Register the current branch and provision a new database.

```bash
python manage.py migraid db add [--alias ALIAS] [--database BASE_ALIAS] [--yes]
```

- `--alias`: The database alias to create in Django. Defaults to a slugified version of your branch name.
- `--database`: An existing database alias to use as a template for the new configuration (copies HOST, USER, PASSWORD, etc.). Defaults to `default`.
- `--yes`: Skip the confirmation prompt.

When you run this command:
1. It derives a new database name from your base configuration.
2. It creates the physical database (Postgres, MySQL, or SQLite).
3. It runs `python manage.py migrate` on the new database.
4. It saves the mapping in `.migraid/config.json`.

### ls

List all branch-database mappings.

```bash
python manage.py migraid db ls
```

Displays a table showing which branches are mapped to which aliases and physical databases, including their current status (e.g., if they are stale).

### rm

Remove a branch's database entry and drop the database.

```bash
python manage.py migraid db rm [--branch BRANCH] [--yes]
```

- `--branch`: The branch to remove. Defaults to the current branch.
- `--yes`: Skip the confirmation prompt.

### prune

Remove database entries for git branches that no longer exist.

```bash
python manage.py migraid db prune [--dry-run] [--yes]
```

- `--dry-run`: Preview which entries would be removed.
- `--yes`: Skip the confirmation prompt.

## Automation

### AUTO_PROVISION_BRANCHES

If you want `django-migraid` to automatically provision a new database whenever you switch to a branch that doesn't have one, set the `AUTO_PROVISION_BRANCHES` environment variable to `TRUE`.

```bash
# In your .env or shell
AUTO_PROVISION_BRANCHES=TRUE
```

When this is enabled, running any `migraid` command on a new branch will:
1. Detect that the branch has no registered database.
2. Derive a new database configuration from your `default` database.
3. Physically create the database.
4. Run `python manage.py migrate` on it.
5. Register it so future commands (including `runserver`) use it automatically.

## How it works

`django-migraid` stores its configuration in a `.migraid/config.json` file in your repository root. You should add `.migraid/` to your `.gitignore` if you don't want to share these mappings with other developers or if they contain credentials.

When you run any `migraid` command, it automatically:
1. Detects the current git branch.
2. If a database mapping exists for that branch, it injects the database configuration into Django's `DATABASES` setting.
3. Automatically uses that database alias if you don't specify one with `--database`.
