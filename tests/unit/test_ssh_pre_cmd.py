from unittest.mock import MagicMock

import pytest

from mtr.ssh import SSHClientWrapper


@pytest.fixture
def mock_paramiko(mocker):
    return mocker.patch("mtr.ssh.paramiko.SSHClient")


def test_exec_stream_with_pre_cmd(mock_paramiko):
    """Test command construction with pre_cmd."""
    client = SSHClientWrapper("1.1.1.1", "user")
    client.client = mock_paramiko.return_value

    # Mock return values
    mock_stdout = MagicMock()
    mock_stdout.__iter__.return_value = []
    client.client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

    # Execute
    list(client.exec_command_stream("python train.py", workdir="/remote", pre_cmd="source activate env"))

    # Verify command string
    expected_cmd = "cd /remote && source activate env && python train.py"
    client.client.exec_command.assert_called_with(expected_cmd, get_pty=True)


def test_exec_stream_no_pre_cmd(mock_paramiko):
    """Test command construction without pre_cmd."""
    client = SSHClientWrapper("1.1.1.1", "user")
    client.client = mock_paramiko.return_value

    mock_stdout = MagicMock()
    mock_stdout.__iter__.return_value = []
    client.client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

    list(client.exec_command_stream("python train.py", workdir="/remote"))

    expected_cmd = "cd /remote && python train.py"
    client.client.exec_command.assert_called_with(expected_cmd, get_pty=True)
