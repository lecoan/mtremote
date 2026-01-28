import os
import select
import socket
import sys
import threading
from typing import Generator, Optional

import paramiko

from mtr.logger import get_logger

# Try to import termios/tty for interactive shell
try:
    import signal
    import termios
    import tty

    HAS_TTY = True
except ImportError:
    HAS_TTY = False


class SSHError(Exception):
    pass


# Constants for interactive shell
DEFAULT_TERMINAL_COLS = 80
DEFAULT_TERMINAL_ROWS = 24
BUFFER_SIZE = 32768  # 32KB for better performance


class SSHClientWrapper:
    def __init__(
        self,
        host: str,
        user: str,
        port: int = 22,
        key_filename: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host
        self.user = user
        self.port = port
        self.key_filename = key_filename
        self.password = password
        self.client: Optional[paramiko.SSHClient] = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "username": self.user,
            "port": self.port,
            "timeout": 10,
        }

        if self.key_filename:
            # Expand user path ~
            expanded_key = os.path.expanduser(self.key_filename)
            connect_kwargs["key_filename"] = expanded_key

        if self.password:
            connect_kwargs["password"] = self.password

        try:
            self.client.connect(**connect_kwargs)
        except paramiko.SSHException as e:
            raise SSHError(f"Failed to connect to {self.host}: {e}")

    def _build_command(self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None) -> str:
        parts = []
        if workdir:
            parts.append(f"cd {workdir}")
        if pre_cmd:
            parts.append(pre_cmd)
        parts.append(command)
        return " && ".join(parts)

    def exec_command_stream(
        self,
        command: str,
        workdir: Optional[str] = None,
        pre_cmd: Optional[str] = None,
        pty: bool = True,
    ) -> Generator[str, None, int]:
        """
        Executes command and yields output lines.
        Returns the exit code.
        Suitable for batch mode or when interactivity is not required.
        """
        if not self.client:
            raise SSHError("Client not connected")

        full_command = self._build_command(command, workdir, pre_cmd)

        try:
            # get_pty=True merges stderr into stdout
            stdin, stdout, stderr = self.client.exec_command(full_command, get_pty=pty)

            # Close stdin as we don't use it in stream mode
            stdin.close()

            # Stream output
            # If pty=False, stdout and stderr are separate.
            # For simplicity in this generator, we only yield stdout if pty=False to avoid
            # interleaving complexity in batch mode,
            # OR we can iterate both. Paramiko buffers them.
            # Let's keep yielding stdout. If pty=True, stderr is in stdout.
            # If pty=False, we might miss stderr here.
            # Improvement: Iterate logic. But for now, let's stick to basic stdout streaming.
            # Users who need stderr separation in batch might need a different method.

            for line in stdout:
                yield line

            # Wait for command to finish and get exit code
            exit_code = stdout.channel.recv_exit_status()
            return exit_code

        except paramiko.SSHException as e:
            raise SSHError(f"Command execution failed: {e}")

    def _setup_channel(self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None):
        """Setup SSH channel with PTY for interactive shell."""
        # Note: self.client is guaranteed to be not None by run_interactive_shell check
        transport = self.client.get_transport()  # type: ignore
        if not transport:
            raise SSHError("Transport not active")

        channel = transport.open_session()

        # Get terminal size
        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            cols, rows = DEFAULT_TERMINAL_COLS, DEFAULT_TERMINAL_ROWS

        channel.get_pty(term=os.environ.get("TERM", "vt100"), width=cols, height=rows)

        full_command = self._build_command(command, workdir, pre_cmd)
        channel.exec_command(full_command)

        return channel

    def _run_event_loop(self, channel) -> int:
        """Run the main event loop for interactive shell."""
        logger = get_logger()
        channel.settimeout(0.0)

        while True:
            r, w, x = select.select([channel, sys.stdin], [], [])

            if channel in r:
                try:
                    data = channel.recv(BUFFER_SIZE)
                    if len(data) == 0:
                        break
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                except socket.error:
                    # Non-blocking mode may raise EAGAIN/EWOULDBLOCK
                    pass
                except Exception as e:
                    logger.warning(f"Error receiving data from channel: {e}", module="mtr.ssh")

            if sys.stdin in r:
                try:
                    data = os.read(sys.stdin.fileno(), BUFFER_SIZE)
                    if len(data) == 0:
                        break
                    channel.send(data)
                except Exception as e:
                    logger.warning(f"Error reading from stdin: {e}", module="mtr.ssh")

        # Wait for exit status with timeout protection
        try:
            channel.settimeout(5.0)
            exit_code = channel.recv_exit_status()
            return exit_code
        except socket.timeout:
            logger.warning("Timeout waiting for exit status, assuming failure", module="mtr.ssh")
            return -1

    def _cleanup_resources(self, channel, old_tty_attrs, old_handler):
        """Cleanup resources with proper error handling."""
        logger = get_logger()

        # Restore terminal settings
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty_attrs)
        except Exception as e:
            logger.warning(f"Failed to restore terminal settings: {e}", module="mtr.ssh")

        # Restore signal handler
        try:
            signal.signal(signal.SIGWINCH, old_handler)
        except Exception as e:
            logger.warning(f"Failed to restore signal handler: {e}", module="mtr.ssh")

        # Close channel
        try:
            if channel:
                channel.close()
        except Exception:
            pass

    def run_interactive_shell(self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None) -> int:
        """
        Runs an interactive shell with PTY support.
        Handles full TTY raw mode, window resizing, and socket forwarding.
        Returns exit code.
        """
        logger = get_logger()

        if not self.client:
            raise SSHError("Client not connected")

        if not HAS_TTY:
            raise SSHError("Interactive mode not supported on this platform (missing termios).")

        # Check if running in main thread (signal safety)
        if threading.current_thread() is not threading.main_thread():
            raise SSHError("Interactive shell must run in main thread")

        # Setup channel
        channel = self._setup_channel(command, workdir, pre_cmd)

        # Create resize handler with proper error handling
        def _resize_handler(signum, frame):
            try:
                if channel and channel.active:
                    c, r = os.get_terminal_size()
                    channel.resize_pty(width=c, height=r)
            except OSError as e:
                logger.debug(f"Failed to resize terminal: {e}", module="mtr.ssh")
            except Exception as e:
                logger.debug(f"Unexpected error in resize handler: {e}", module="mtr.ssh")

        # Save old states BEFORE setting up new ones (avoid race condition)
        old_tty_attrs = termios.tcgetattr(sys.stdin)
        old_handler = signal.signal(signal.SIGWINCH, _resize_handler)

        # Enter raw mode AFTER saving old state
        tty.setraw(sys.stdin.fileno())

        try:
            exit_code = self._run_event_loop(channel)
            return exit_code
        finally:
            self._cleanup_resources(channel, old_tty_attrs, old_handler)

    def close(self):
        if self.client:
            self.client.close()
