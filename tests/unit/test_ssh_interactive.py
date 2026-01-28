"""Tests for SSH interactive shell functionality using ssh -t command."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from mtr.ssh import SSHClientWrapper, SSHError, _check_ssh_availability, _check_sshpass_availability


class TestCheckSSHAvailability:
    """Test suite for _check_ssh_availability function."""

    @patch("mtr.ssh.shutil.which")
    def test_ssh_available(self, mock_which):
        """Test that function passes when ssh is available."""
        mock_which.return_value = "/usr/bin/ssh"
        # Should not raise
        _check_ssh_availability()

    @patch("mtr.ssh.shutil.which")
    def test_ssh_not_available(self, mock_which):
        """Test that function raises SSHError when ssh is not available."""
        mock_which.return_value = None
        with pytest.raises(SSHError, match="SSH command not found"):
            _check_ssh_availability()


class TestCheckSshpassAvailability:
    """Test suite for _check_sshpass_availability function."""

    @patch("mtr.ssh.shutil.which")
    def test_sshpass_available(self, mock_which):
        """Test that function passes when sshpass is available."""
        mock_which.return_value = "/usr/bin/sshpass"
        # Should not raise
        _check_sshpass_availability()

    @patch("mtr.ssh.shutil.which")
    def test_sshpass_not_available(self, mock_which):
        """Test that function raises SSHError when sshpass is not available."""
        mock_which.return_value = None
        with pytest.raises(SSHError, match="sshpass command not found"):
            _check_sshpass_availability()


class TestRunInteractiveShell:
    """Test suite for run_interactive_shell method using ssh -t."""

    @pytest.fixture
    def mock_ssh_client(self):
        """Create a mock SSH client."""
        client = SSHClientWrapper("test-host", "test-user")
        return client

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_basic_execution(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test basic interactive shell execution with key authentication."""
        mock_run.return_value = Mock(returncode=0)
        mock_ssh_client.key_filename = "~/.ssh/id_rsa"

        exit_code = mock_ssh_client.run_interactive_shell("echo hello")

        assert exit_code == 0
        mock_check_ssh.assert_called_once()
        mock_run.assert_called_once()
        # Verify ssh command structure
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "ssh"
        assert "-t" in call_args
        assert "-i" in call_args
        assert "test-user@test-host" in call_args
        assert "echo hello" in call_args

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh._check_sshpass_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_password_authentication(self, mock_run, mock_check_sshpass, mock_check_ssh, mock_ssh_client):
        """Test interactive shell with password authentication using sshpass."""
        mock_run.return_value = Mock(returncode=0)
        mock_ssh_client.password = "secret123"

        exit_code = mock_ssh_client.run_interactive_shell("echo hello")

        assert exit_code == 0
        mock_check_ssh.assert_called_once()
        mock_check_sshpass.assert_called_once()
        mock_run.assert_called_once()
        # Verify sshpass wrapper
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "sshpass"
        assert call_args[1] == "-p"
        assert call_args[2] == "secret123"
        assert "ssh" in call_args

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_with_workdir(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test interactive shell with working directory."""
        mock_run.return_value = Mock(returncode=0)

        exit_code = mock_ssh_client.run_interactive_shell("ls", workdir="/tmp")

        assert exit_code == 0
        call_args = mock_run.call_args[0][0]
        command = call_args[-1]  # Last element is the command
        assert "cd /tmp" in command
        assert "ls" in command

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_with_pre_cmd(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test interactive shell with pre-command."""
        mock_run.return_value = Mock(returncode=0)

        exit_code = mock_ssh_client.run_interactive_shell("python script.py", pre_cmd="source ~/.bashrc")

        assert exit_code == 0
        call_args = mock_run.call_args[0][0]
        command = call_args[-1]
        assert "source ~/.bashrc" in command
        assert "python script.py" in command

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_with_port(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test interactive shell with non-default port."""
        mock_run.return_value = Mock(returncode=0)
        mock_ssh_client.port = 2222

        exit_code = mock_ssh_client.run_interactive_shell("echo hello")

        assert exit_code == 0
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args
        assert "2222" in call_args

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_default_port_not_included(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test that default port (22) is not included in command."""
        mock_run.return_value = Mock(returncode=0)
        mock_ssh_client.port = 22

        exit_code = mock_ssh_client.run_interactive_shell("echo hello")

        assert exit_code == 0
        call_args = mock_run.call_args[0][0]
        # -p should not be in the command for default port
        assert "-p" not in call_args

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_non_zero_exit_code(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test that non-zero exit code is properly returned."""
        mock_run.return_value = Mock(returncode=1)

        exit_code = mock_ssh_client.run_interactive_shell("false")

        assert exit_code == 1

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_ssh_not_found_error(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test handling of FileNotFoundError during subprocess execution."""
        mock_run.side_effect = FileNotFoundError("ssh not found")

        with pytest.raises(SSHError, match="SSH command execution failed"):
            mock_ssh_client.run_interactive_shell("echo hello")

    @patch("mtr.ssh._check_ssh_availability")
    @patch("mtr.ssh.subprocess.run")
    def test_generic_subprocess_error(self, mock_run, mock_check_ssh, mock_ssh_client):
        """Test handling of generic subprocess errors."""
        mock_run.side_effect = Exception("Some error")

        with pytest.raises(SSHError, match="Interactive shell failed"):
            mock_ssh_client.run_interactive_shell("echo hello")

    @patch("mtr.ssh.shutil.which")
    def test_ssh_check_fails_before_execution(self, mock_which, mock_ssh_client):
        """Test that SSH availability is checked before attempting execution."""
        mock_which.return_value = None

        with pytest.raises(SSHError, match="SSH command not found"):
            mock_ssh_client.run_interactive_shell("echo hello")

    @patch("mtr.ssh.shutil.which")
    def test_sshpass_check_fails_with_password(self, mock_which, mock_ssh_client):
        """Test that sshpass availability is checked when password is used."""
        mock_ssh_client.password = "secret"
        # First call (ssh) succeeds, second call (sshpass) fails
        mock_which.side_effect = ["/usr/bin/ssh", None]

        with pytest.raises(SSHError, match="sshpass command not found"):
            mock_ssh_client.run_interactive_shell("echo hello")


class TestBuildCommand:
    """Test suite for _build_command helper method."""

    def test_basic_command(self):
        """Test building command without workdir or pre_cmd."""
        client = SSHClientWrapper("host", "user")
        result = client._build_command("echo hello")
        assert result == "echo hello"

    def test_with_workdir(self):
        """Test building command with workdir."""
        client = SSHClientWrapper("host", "user")
        result = client._build_command("ls", workdir="/tmp")
        assert result == "cd /tmp && ls"

    def test_with_pre_cmd(self):
        """Test building command with pre_cmd."""
        client = SSHClientWrapper("host", "user")
        result = client._build_command("python app.py", pre_cmd="source venv/bin/activate")
        assert result == "source venv/bin/activate && python app.py"

    def test_with_workdir_and_pre_cmd(self):
        """Test building command with both workdir and pre_cmd."""
        client = SSHClientWrapper("host", "user")
        result = client._build_command("python app.py", workdir="/app", pre_cmd="source venv/bin/activate")
        assert result == "cd /app && source venv/bin/activate && python app.py"

    def test_empty_workdir(self):
        """Test that empty workdir is ignored."""
        client = SSHClientWrapper("host", "user")
        result = client._build_command("ls", workdir="")
        assert result == "ls"

    def test_empty_pre_cmd(self):
        """Test that empty pre_cmd is ignored."""
        client = SSHClientWrapper("host", "user")
        result = client._build_command("ls", pre_cmd="")
        assert result == "ls"


class TestExecCommandStream:
    """Test suite for exec_command_stream method (batch mode, still uses paramiko)."""

    @pytest.fixture
    def mock_ssh_client(self):
        """Create a mock SSH client with connected state."""
        client = SSHClientWrapper("test-host", "test-user")
        client.client = MagicMock()
        return client

    def test_not_connected_raises_error(self):
        """Test that running without connection raises SSHError."""
        client = SSHClientWrapper("test-host", "test-user")
        with pytest.raises(SSHError, match="Client not connected"):
            list(client.exec_command_stream("echo hello"))

    def test_successful_execution(self, mock_ssh_client):
        """Test successful batch command execution."""
        mock_stdout = MagicMock()
        mock_stdout.__iter__ = Mock(return_value=iter(["line1\n", "line2\n"]))
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_ssh_client.client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

        result = list(mock_ssh_client.exec_command_stream("echo hello"))

        assert result == ["line1\n", "line2\n"]
        mock_ssh_client.client.exec_command.assert_called_once()

    def test_exit_code_returned(self, mock_ssh_client):
        """Test that exit code is properly returned via StopIteration."""
        mock_stdout = MagicMock()
        mock_stdout.__iter__ = Mock(return_value=iter([]))
        mock_stdout.channel.recv_exit_status.return_value = 42

        mock_ssh_client.client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

        stream = mock_ssh_client.exec_command_stream("false")
        exit_code = None
        try:
            while True:
                next(stream)
        except StopIteration as e:
            exit_code = e.value

        assert exit_code == 42

    def test_command_building_with_workdir_and_pre_cmd(self, mock_ssh_client):
        """Test that workdir and pre_cmd are properly included in command."""
        mock_stdout = MagicMock()
        mock_stdout.__iter__ = Mock(return_value=iter([]))
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_ssh_client.client.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

        list(mock_ssh_client.exec_command_stream("ls", workdir="/tmp", pre_cmd="source env"))

        call_args = mock_ssh_client.client.exec_command.call_args[0]
        assert "cd /tmp" in call_args[0]
        assert "source env" in call_args[0]
        assert "ls" in call_args[0]
