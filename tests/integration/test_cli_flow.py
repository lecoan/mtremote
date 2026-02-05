import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mtr.cli import cli


@pytest.fixture
def mock_components(mocker):
    config_mock = mocker.patch("mtr.cli.ConfigLoader")
    sync_mock = mocker.patch("mtr.cli.RsyncSyncer")
    return config_mock, sync_mock


def test_mtr_flow(mock_components):
    config_cls, sync_cls = mock_components

    # Setup Config Mock
    mock_config_instance = MagicMock()
    mock_config_instance.target_server = "gpu-01"
    mock_config_instance.server_config = {
        "host": "1.2.3.4",
        "user": "testuser",
        "key_filename": "key",
        "remote_dir": "/remote",
        "sync": "rsync",
    }
    mock_config_instance.global_defaults = {"exclude": []}
    config_cls.return_value.load.return_value = mock_config_instance

    # Setup Sync Mock
    sync_instance = sync_cls.return_value

    # Mock SSH command execution
    with patch("mtr.cli.run_ssh_command") as mock_ssh:
        mock_ssh.return_value = 0

        runner = CliRunner()
        # Invoke with arguments. Note: command is passed as args
        result = runner.invoke(cli, ["python", "train.py"])

        assert result.exit_code == 0

        # Verify Call Order
        config_cls.return_value.load.assert_called()
        sync_cls.assert_called()
        sync_instance.sync.assert_called()
        mock_ssh.assert_called_once()

        # Verify SSH command was called with correct arguments
        call_kwargs = mock_ssh.call_args.kwargs
        assert call_kwargs["host"] == "1.2.3.4"
        assert call_kwargs["user"] == "testuser"
        assert call_kwargs["command"] == "python train.py"
        assert call_kwargs["workdir"] == "/remote"


def test_mtr_init(tmp_path):
    """Test mtr --init creates configuration file."""
    runner = CliRunner()

    # Switch to tmp_path
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["--init"])

        assert result.exit_code == 0
        assert "Created configuration" in result.output

        config_path = os.path.join(os.getcwd(), ".mtr", "config.yaml")
        assert os.path.exists(config_path)

        with open(config_path, "r") as f:
            content = f.read()
            assert "MTRemote Configuration" in content
            assert "dev-node" in content
