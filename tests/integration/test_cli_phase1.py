from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mtr.cli import cli


@pytest.fixture
def mock_components(mocker):
    config_mock = mocker.patch("mtr.cli.ConfigLoader")
    rsync_mock = mocker.patch("mtr.cli.RsyncSyncer")
    return config_mock, rsync_mock


def test_sftp_config_rejected(mock_components):
    """Test that SFTP configuration is rejected with error."""
    config_cls, rsync_cls = mock_components

    # Config for SFTP (should be rejected)
    mock_config = MagicMock()
    mock_config.target_server = "server-sftp"
    mock_config.server_config = {
        "host": "1.1.1.1",
        "user": "user",
        "password": "pwd",
        "remote_dir": "/remote",
        "sync": "sftp",  # Explicit sftp - should fail
    }
    mock_config.global_defaults = {"exclude": []}
    config_cls.return_value.load.return_value = mock_config

    runner = CliRunner()
    result = runner.invoke(cli, ["ls"])

    # Should exit with error code 1
    assert result.exit_code == 1
    assert "SFTP mode has been removed" in result.output


def test_cli_pre_cmd_flow(mock_components):
    """Test that pre_cmd is passed to ssh execution."""
    config_cls, rsync_cls = mock_components

    mock_config = MagicMock()
    mock_config.target_server = "server-precmd"
    mock_config.server_config = {
        "host": "1.1.1.1",
        "user": "user",
        "key_filename": "key",
        "remote_dir": "/remote",
        "pre_cmd": "source .env",
    }
    mock_config.global_defaults = {"exclude": []}
    config_cls.return_value.load.return_value = mock_config

    with patch("mtr.cli.run_ssh_command") as mock_ssh:
        mock_ssh.return_value = 0

        runner = CliRunner()
        result = runner.invoke(cli, ["python main.py"])

        assert result.exit_code == 0

        # Verify pre_cmd was passed
        call_kwargs = mock_ssh.call_args.kwargs
        assert call_kwargs["pre_cmd"] == "source .env"
