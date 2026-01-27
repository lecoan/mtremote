from unittest.mock import MagicMock

import pytest

from mtr.ssh import SSHClientWrapper


@pytest.fixture
def mock_paramiko(mocker):
    return mocker.patch("mtr.ssh.paramiko.SSHClient")


def test_connect_key(mock_paramiko):
    client = SSHClientWrapper("1.1.1.1", "user", key_filename="/path/to/key")
    client.connect()

    mock_instance = mock_paramiko.return_value
    mock_instance.connect.assert_called_with(
        hostname="1.1.1.1",
        username="user",
        port=22,
        key_filename="/path/to/key",
        timeout=10,
    )


def test_connect_password(mock_paramiko):
    client = SSHClientWrapper("1.1.1.1", "user", password="password")
    client.connect()

    mock_instance = mock_paramiko.return_value
    mock_instance.connect.assert_called_with(hostname="1.1.1.1", username="user", port=22, password="password", timeout=10)


def test_exec_stream(mock_paramiko):
    client = SSHClientWrapper("1.1.1.1", "user")
    client.client = mock_paramiko.return_value  # Inject mock

    # Mock exec_command return values
    mock_stdout = MagicMock()
    mock_stdout.__iter__.return_value = ["line1\n", "line2\n"]

    mock_stderr = MagicMock()

    # exec_command returns (stdin, stdout, stderr)
    client.client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

    # We expect the generator to yield lines.
    # Note: Real implementation might handle stdout/stderr interleaving.
    # For this simple test, we just check if it calls exec_command.

    generator = client.exec_command_stream("echo hello")

    # Consume generator
    results = list(generator)

    client.client.exec_command.assert_called_with("echo hello", get_pty=True)

    # Verify we got some output (implementation dependent on how we interleave)
    assert any("line1" in str(r) for r in results)
