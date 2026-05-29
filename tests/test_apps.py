import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps
from migraid.apps import MigraidConfig

def test_migraid_config_metadata():
    app_config = apps.get_app_config("migraid")
    assert app_config.name == "migraid"
    assert app_config.verbose_name == "Migration Aid"

@patch("migraid.operations.branch_db.find_git_root")
@patch("migraid.operations.branch_db.current_git_branch")
@patch("migraid.operations.branch_db.BranchDBConfig.load")
@patch("migraid.operations.branch_db.provision_branch_db")
def test_ready_auto_provision(mock_provision, mock_load, mock_branch, mock_find_root):
    # Setup mocks
    mock_find_root.return_value = Path("/fake/root")
    mock_branch.return_value = "feature-branch"
    
    mock_cfg = MagicMock()
    mock_cfg.get_entry.return_value = None
    mock_load.return_value = mock_cfg
    
    # Set env var
    with patch.dict(os.environ, {"AUTO_PROVISION_BRANCHES": "TRUE"}):
        config = MigraidConfig("migraid", sys.modules[__name__])
        config.ready()
        
    mock_provision.assert_called_once_with(mock_cfg, "feature-branch")

@patch("migraid.operations.branch_db.find_git_root")
@patch("migraid.operations.branch_db.current_git_branch")
@patch("migraid.operations.branch_db.BranchDBConfig.load")
def test_ready_no_git_root(mock_load, mock_branch, mock_find_root):
    mock_find_root.return_value = None
    
    config = MigraidConfig("migraid", sys.modules[__name__])
    config.ready()
    
    mock_load.assert_not_called()

@patch("migraid.operations.branch_db.find_git_root")
@patch("migraid.operations.branch_db.current_git_branch")
@patch("migraid.operations.branch_db.BranchDBConfig.load")
def test_ready_no_branch(mock_load, mock_branch, mock_find_root):
    mock_find_root.return_value = Path("/fake/root")
    mock_branch.return_value = None
    
    config = MigraidConfig("migraid", sys.modules[__name__])
    config.ready()
    
    mock_load.assert_called_once()
    mock_cfg = mock_load.return_value
    mock_cfg.inject_all.assert_called_once()

@patch("migraid.operations.branch_db.find_git_root")
def test_ready_skip_during_db_commands(mock_find_root):
    with patch.object(sys, "argv", ["manage.py", "migraid", "db", "add"]):
        config = MigraidConfig("migraid", sys.modules[__name__])
        config.ready()
        mock_find_root.assert_not_called()

@patch("migraid.operations.branch_db.find_git_root")
@patch("migraid.operations.branch_db.current_git_branch")
@patch("migraid.operations.branch_db.BranchDBConfig.load")
@patch("migraid.operations.branch_db.provision_branch_db")
def test_ready_auto_provision_failure(mock_provision, mock_load, mock_branch, mock_find_root):
    mock_find_root.return_value = Path("/fake/root")
    mock_branch.return_value = "feature-branch"
    mock_cfg = MagicMock()
    mock_cfg.get_entry.return_value = None
    mock_load.return_value = mock_cfg
    mock_provision.side_effect = Exception("creation failed")
    
    with patch.dict(os.environ, {"AUTO_PROVISION_BRANCHES": "TRUE"}):
        config = MigraidConfig("migraid", sys.modules[__name__])
        # Should not raise exception, just print to stderr
        config.ready()
        
    mock_provision.assert_called_once()
