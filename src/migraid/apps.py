import os
import sys

from django.apps import AppConfig


class MigraidConfig(AppConfig):
    name = "migraid"
    verbose_name = "Migration Aid"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Auto-inject branch databases and handle auto-provisioning."""
        # Avoid running during common management commands that shouldn't trigger this,
        # or if we are already inside a migraid subcommand handler to avoid recursion.
        if "migraid" in sys.argv and "db" in sys.argv:
            return

        from .operations.branch_db import (
            BranchDBConfig,
            current_git_branch,
            find_git_root,
            provision_branch_db,
        )

        git_root = find_git_root()
        if not git_root:
            return

        cfg = BranchDBConfig.load(git_root)
        cfg.inject_all()

        branch = current_git_branch()
        if not branch:
            return

        # Feature: AUTO_PROVISION_BRANCHES=TRUE
        auto_provision = os.environ.get("AUTO_PROVISION_BRANCHES", "").lower() == "true"
        if auto_provision and cfg.get_entry(branch) is None:
            # We use a simple print here as ConsoleOutput might not be fully ready/appropriate
            print(f"migraid: Auto-provisioning DB for branch '{branch}'...")
            try:
                provision_branch_db(cfg, branch)
                print(f"migraid: Success! Registered database for '{branch}'.")
            except Exception as exc:
                print(f"migraid: Auto-provisioning failed: {exc}", file=sys.stderr)

        # Auto-resolve the database for the current branch
        entry = cfg.get_entry(branch)
        if entry:
            # We can't easily modify 'options' here for other commands, but we
            # can ensure the connection is ready. Django's database routing
            # or manual --database ALIAS is still preferred, but for runserver,
            # injecting the config is enough if they use the alias.
            pass
