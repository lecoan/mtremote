"""Tests for SSH interactive shell functionality."""

import socket
from unittest.mock import MagicMock, Mock, patch

import pytest

from mtr.ssh import SSHClientWrapper, SSHError


class TestRunInteractiveShell:
    """Test suite for run_interactive_shell method."""

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
            client.run_interactive_shell("echo hello")

    @patch("mtr.ssh.HAS_TTY", False)
    def test_no_tty_support_raises_error(self, mock_ssh_client):
        """Test that missing TTY support raises SSHError."""
        with pytest.raises(SSHError, match="Interactive mode not supported"):
            mock_ssh_client.run_interactive_shell("echo hello")

    @patch("threading.current_thread")
    @patch("threading.main_thread")
    def test_non_main_thread_raises_error(self, mock_main_thread, mock_current_thread, mock_ssh_client):
        """Test that running in non-main thread raises SSHError."""
        mock_thread = Mock()
        mock_current_thread.return_value = mock_thread
        mock_main_thread.return_value = Mock()  # Different from current_thread

        with pytest.raises(SSHError, match="main thread"):
            mock_ssh_client.run_interactive_shell("echo hello")


class TestSetupChannel:
    """Test suite for _setup_channel helper method."""

    def test_transport_not_active_raises_error(self):
        """Test that inactive transport raises SSHError."""
        client = SSHClientWrapper("test-host", "test-user")
        client.client = MagicMock()
        client.client.get_transport.return_value = None

        with pytest.raises(SSHError, match="Transport not active"):
            client._setup_channel("echo hello")

    def test_successful_channel_setup(self):
        """Test successful channel setup with PTY."""
        client = SSHClientWrapper("test-host", "test-user")
        client.client = MagicMock()

        mock_transport = MagicMock()
        client.client.get_transport.return_value = mock_transport

        mock_channel = MagicMock()
        mock_transport.open_session.return_value = mock_channel

        # Execute
        channel = client._setup_channel("echo hello", workdir="/tmp", pre_cmd="source env")

        # Verify
        assert channel == mock_channel
        mock_channel.get_pty.assert_called_once()
        mock_channel.exec_command.assert_called_once()
        # Verify command includes workdir and pre_cmd
        call_args = mock_channel.exec_command.call_args[0][0]
        assert "cd /tmp" in call_args
        assert "source env" in call_args
        assert "echo hello" in call_args

    @patch("os.get_terminal_size")
    def test_terminal_size_fallback(self, mock_get_size):
        """Test fallback to default terminal size on OSError."""
        client = SSHClientWrapper("test-host", "test-user")
        client.client = MagicMock()

        mock_transport = MagicMock()
        client.client.get_transport.return_value = mock_transport

        mock_channel = MagicMock()
        mock_transport.open_session.return_value = mock_channel

        # Make get_terminal_size fail
        mock_get_size.side_effect = OSError("Not a tty")

        # Execute
        client._setup_channel("echo hello")

        # Verify default size was used
        mock_channel.get_pty.assert_called_once()
        call_kwargs = mock_channel.get_pty.call_args[1]
        assert call_kwargs["width"] == 80
        assert call_kwargs["height"] == 24


class TestRunEventLoop:
    """Test suite for _run_event_loop method."""

    @pytest.fixture
    def mock_ssh_client(self):
        """Create a mock SSH client with connected state."""
        client = SSHClientWrapper("test-host", "test-user")
        client.client = MagicMock()
        return client

    @pytest.fixture
    def mock_channel(self):
        """Create a mock SSH channel."""
        channel = MagicMock()
        channel.active = True
        channel.recv.return_value = b""
        channel.recv_exit_status.return_value = 0
        return channel

    @patch("mtr.ssh.select.select")
    @patch("os.read")
    @patch("sys.stdout.buffer.write")
    @patch("sys.stdout.buffer.flush")
    def test_successful_execution(self, mock_flush, mock_write, mock_os_read, mock_select, mock_ssh_client, mock_channel):
        """Test successful event loop execution."""
        # Setup mocks - need enough side_effects for all select calls
        mock_select.side_effect = [
            ([mock_channel], [], []),  # Channel has data
            ([mock_channel], [], []),  # EOF from channel
            ([], [], []),  # Empty select
        ]

        mock_channel.recv.side_effect = [b"output\n", b""]  # Data then EOF
        mock_os_read.return_value = b""  # Stdin EOF

        # Execute
        exit_code = mock_ssh_client._run_event_loop(mock_channel)

        # Verify
        assert exit_code == 0
        # settimeout is called twice: once with 0.0 (non-blocking), then 5.0 (for exit status)
        assert mock_channel.settimeout.call_count == 2
        mock_channel.settimeout.assert_any_call(0.0)
        mock_channel.settimeout.assert_any_call(5.0)
        mock_write.assert_called_once_with(b"output\n")
        mock_flush.assert_called_once()

    @patch("mtr.ssh.select.select")
    @patch("os.read")
    def test_channel_recv_error_handling(self, mock_os_read, mock_select, mock_ssh_client, mock_channel):
        """Test that socket errors during recv are handled gracefully."""
        # Setup mocks - need enough side_effects
        mock_select.side_effect = [
            ([mock_channel], [], []),
            ([mock_channel], [], []),
            ([mock_channel], [], []),
            ([], [], []),
        ]

        # Simulate socket error then success
        mock_channel.recv.side_effect = [
            socket.error("EAGAIN"),  # First call raises error
            b"output\n",  # Second call succeeds
            b"",  # EOF
        ]

        mock_os_read.return_value = b""
        mock_channel.recv_exit_status.return_value = 0

        with patch("mtr.ssh.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Execute - should not raise
            exit_code = mock_ssh_client._run_event_loop(mock_channel)
            assert exit_code == 0

    @patch("mtr.ssh.select.select")
    def test_exit_status_timeout(self, mock_select, mock_ssh_client, mock_channel):
        """Test handling of timeout when waiting for exit status."""
        # Setup mocks
        mock_select.side_effect = [
            ([mock_channel], [], []),
            ([], [], []),
        ]
        mock_channel.recv.return_value = b""

        # Simulate timeout on exit status
        mock_channel.recv_exit_status.side_effect = socket.timeout("Timeout")

        with patch("mtr.ssh.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Execute - should return -1 on timeout
            exit_code = mock_ssh_client._run_event_loop(mock_channel)
            assert exit_code == -1

            # Verify warning was logged
            mock_logger.warning.assert_called_with("Timeout waiting for exit status, assuming failure", module="mtr.ssh")

    @patch("mtr.ssh.select.select")
    @patch("os.read")
    def test_stdin_eof_handling(self, mock_os_read, mock_select, mock_ssh_client, mock_channel):
        """Test that stdin EOF properly terminates the loop."""
        # Setup mocks - need enough side_effects for all iterations
        mock_select.side_effect = [
            ([], [mock_channel], []),  # Stdin has data
            ([mock_channel], [], []),  # Channel EOF
            ([], [], []),  # Empty to exit
        ]

        mock_channel.recv.return_value = b""
        mock_os_read.return_value = b""  # EOF
        mock_channel.recv_exit_status.return_value = 0

        # Execute
        exit_code = mock_ssh_client._run_event_loop(mock_channel)

        # Verify
        assert exit_code == 0
        mock_channel.send.assert_not_called()  # Should not send empty data


class TestCleanupResources:
    """Test suite for _cleanup_resources method."""

    @pytest.fixture
    def mock_ssh_client(self):
        """Create a mock SSH client."""
        client = SSHClientWrapper("test-host", "test-user")
        client.client = MagicMock()
        return client

    @pytest.fixture
    def mock_channel(self):
        """Create a mock SSH channel."""
        return MagicMock()

    @patch("termios.tcsetattr")
    @patch("signal.signal")
    def test_successful_cleanup(self, mock_signal, mock_tcsetattr, mock_ssh_client, mock_channel):
        """Test successful resource cleanup."""
        old_attrs = ["old_tty_attrs"]
        old_handler = Mock()

        mock_ssh_client._cleanup_resources(mock_channel, old_attrs, old_handler)

        mock_tcsetattr.assert_called_once()
        mock_signal.assert_called_once()
        mock_channel.close.assert_called_once()

    @patch("termios.tcsetattr")
    @patch("signal.signal")
    def test_cleanup_continues_on_terminal_error(self, mock_signal, mock_tcsetattr, mock_ssh_client, mock_channel):
        """Test that cleanup continues even if terminal restore fails."""
        old_attrs = ["old_tty_attrs"]
        old_handler = Mock()

        # Make terminal restore fail
        mock_tcsetattr.side_effect = OSError("Failed to restore")

        with patch("mtr.ssh.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Execute - should not raise
            mock_ssh_client._cleanup_resources(mock_channel, old_attrs, old_handler)

            # Verify warning was logged
            mock_logger.warning.assert_called()
            # Verify other cleanup still happened
            mock_signal.assert_called_once()
            mock_channel.close.assert_called_once()

    @patch("termios.tcsetattr")
    @patch("signal.signal")
    def test_cleanup_continues_on_signal_error(self, mock_signal, mock_tcsetattr, mock_ssh_client, mock_channel):
        """Test that cleanup continues even if signal restore fails."""
        old_attrs = ["old_tty_attrs"]
        old_handler = Mock()

        # Make signal restore fail
        mock_signal.side_effect = OSError("Failed to restore")

        with patch("mtr.ssh.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Execute - should not raise
            mock_ssh_client._cleanup_resources(mock_channel, old_attrs, old_handler)

            # Verify warning was logged
            mock_logger.warning.assert_called()
            # Verify channel close still happened
            mock_channel.close.assert_called_once()

    @patch("termios.tcsetattr")
    @patch("signal.signal")
    def test_cleanup_with_none_channel(self, mock_signal, mock_tcsetattr, mock_ssh_client):
        """Test cleanup when channel is None."""
        old_attrs = ["old_tty_attrs"]
        old_handler = Mock()

        # Execute with None channel - should not raise
        mock_ssh_client._cleanup_resources(None, old_attrs, old_handler)

        mock_tcsetattr.assert_called_once()
        mock_signal.assert_called_once()
        # No error for None channel
