from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from mtr.cli import cli


@pytest.fixture
def mock_components(mocker):
    config_mock = mocker.patch("mtr.cli.ConfigLoader")
    ssh_mock = mocker.patch("mtr.cli.SSHClientWrapper")
    # Patch both classes
    rsync_mock = mocker.patch("mtr.cli.RsyncSyncer")
    sftp_mock = mocker.patch("mtr.cli.SftpSyncer")
    return config_mock, ssh_mock, rsync_mock, sftp_mock


def test_sftp_sync_mode(mock_components):
    """Test that SftpSyncer is used when engine=sftp is configured."""
    config_cls, ssh_cls, rsync_cls, sftp_cls = mock_components

    # Config for SFTP
    mock_config = MagicMock()
    mock_config.target_server = "server-sftp"
    mock_config.server_config = {
        "host": "1.1.1.1",
        "user": "user",
        "password": "pwd",
        "remote_dir": "/remote",
        "sync": "sftp",  # Explicit sftp
    }
    mock_config.global_defaults = {"exclude": []}
    config_cls.return_value.load.return_value = mock_config

    ssh_cls.return_value.exec_command_stream.side_effect = lambda *args, **kwargs: (yield "done")

    runner = CliRunner()
    result = runner.invoke(cli, ["ls"])

    assert result.exit_code == 0
    # Rsync should NOT be called
    rsync_cls.assert_not_called()
    # SFTP SHOULD be called
    sftp_cls.assert_called_once()
    sftp_cls.return_value.sync.assert_called_once()


def test_cli_pre_cmd_flow(mock_components):
    """Test that pre_cmd is passed to ssh execution."""
    config_cls, ssh_cls, _, _ = mock_components

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

    ssh_instance = ssh_cls.return_value
    ssh_instance.exec_command_stream.side_effect = lambda *args, **kwargs: (yield "done")

    runner = CliRunner()
    result = runner.invoke(cli, ["python main.py"])

    assert result.exit_code == 0

    # Verify pre_cmd was passed
    call_args = ssh_instance.exec_command_stream.call_args
    assert call_args.kwargs["pre_cmd"] == "source .env"
