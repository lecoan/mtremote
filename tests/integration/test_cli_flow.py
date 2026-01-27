import os
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from mtr.cli import cli


@pytest.fixture
def mock_components(mocker):
    config_mock = mocker.patch("mtr.cli.ConfigLoader")
    ssh_mock = mocker.patch("mtr.cli.SSHClientWrapper")
    sync_mock = mocker.patch("mtr.cli.RsyncSyncer")
    return config_mock, ssh_mock, sync_mock


def test_mtr_flow(mock_components):
    config_cls, ssh_cls, sync_cls = mock_components

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

    # Setup SSH Mock with generator return value
    ssh_instance = ssh_cls.return_value

    def mock_stream(*args, **kwargs):
        yield "output line 1"
        return 0

    ssh_instance.exec_command_stream.side_effect = mock_stream

    # Setup Sync Mock
    sync_instance = sync_cls.return_value

    runner = CliRunner()
    # Invoke with arguments. Note: command is passed as args
    result = runner.invoke(cli, ["python", "train.py"])

    assert result.exit_code == 0

    # Verify Call Order
    config_cls.return_value.load.assert_called()
    sync_cls.assert_called()
    sync_instance.sync.assert_called()
    ssh_cls.assert_called()
    ssh_instance.connect.assert_called()
    ssh_instance.exec_command_stream.assert_called()

    args, kwargs = ssh_instance.exec_command_stream.call_args
    assert "python train.py" in args[0]
    assert kwargs["workdir"] == "/remote"


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
