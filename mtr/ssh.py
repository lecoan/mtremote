import os
import select
import socket
import sys
import threading
from typing import Generator, Optional

import paramiko

from mtr.logger import get_logger

# Module-level logger instance
logger = get_logger()

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
        logger.info(f"Connecting to {self.host}:{self.port} as {self.user}", module="mtr.ssh")
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "username": self.user,
            "port": self.port,
            "timeout": 10,
        }

        if self.key_filename:
            expanded_key = os.path.expanduser(self.key_filename)
            connect_kwargs["key_filename"] = expanded_key
            logger.info("Using key-based authentication", module="mtr.ssh")
        elif self.password:
            connect_kwargs["password"] = self.password
            logger.info("Using password authentication", module="mtr.ssh")
        else:
            logger.info("No authentication method specified, using default", module="mtr.ssh")

        try:
            self.client.connect(**connect_kwargs)
            logger.info(f"SSH connection established to {self.host}", module="mtr.ssh")
        except paramiko.SSHException as e:
            logger.error(f"Failed to connect to {self.host}: {e}", module="mtr.ssh")
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
        logger.info(f"Executing command (stream mode): {command}", module="mtr.ssh")
        logger.debug(f"Workdir: {workdir}, Pre-cmd: {pre_cmd}, PTY: {pty}", module="mtr.ssh")

        if not self.client:
            raise SSHError("Client not connected")

        full_command = self._build_command(command, workdir, pre_cmd)
        logger.debug(f"Full command: {full_command}", module="mtr.ssh")

        try:
            stdin, stdout, stderr = self.client.exec_command(full_command, get_pty=pty)
            stdin.close()

            logger.debug("Command executed, starting output stream", module="mtr.ssh")

            line_count = 0
            for line in stdout:
                line_count += 1
                if line_count % 100 == 0:
                    logger.debug(f"Streamed {line_count} lines so far", module="mtr.ssh")
                yield line

            logger.debug(f"Output stream ended, total lines: {line_count}", module="mtr.ssh")

            exit_code = stdout.channel.recv_exit_status()
            logger.info(f"Command exited with code: {exit_code}", module="mtr.ssh")
            return exit_code

        except paramiko.SSHException as e:
            logger.error(f"Command execution failed: {e}", module="mtr.ssh")
            raise SSHError(f"Command execution failed: {e}")

    def _setup_channel(self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None):
        """Setup SSH channel with PTY for interactive shell."""
        logger.debug("Opening SSH transport session", module="mtr.ssh")
        transport = self.client.get_transport()  # type: ignore
        if not transport:
            raise SSHError("Transport not active")

        channel = transport.open_session()

        try:
            cols, rows = os.get_terminal_size()
            logger.debug(f"Terminal size detected: {cols}x{rows}", module="mtr.ssh")
        except OSError:
            cols, rows = DEFAULT_TERMINAL_COLS, DEFAULT_TERMINAL_ROWS
            logger.debug(f"Failed to get terminal size, using default: {cols}x{rows}", module="mtr.ssh")

        term = os.environ.get("TERM", "vt100")
        logger.debug(f"Terminal type: {term}", module="mtr.ssh")

        logger.debug("Requesting PTY allocation", module="mtr.ssh")
        channel.get_pty(term=term, width=cols, height=rows)

        full_command = self._build_command(command, workdir, pre_cmd)
        logger.debug(f"Executing command: {full_command}", module="mtr.ssh")
        channel.exec_command(full_command)

        logger.debug("Channel setup completed", module="mtr.ssh")
        return channel

    def _run_event_loop(self, channel) -> int:
        """Run the main event loop for interactive shell."""
        logger.debug("Setting channel to non-blocking mode (timeout=0.0)", module="mtr.ssh")
        channel.settimeout(0.0)

        iteration = 0
        total_bytes_received = 0
        total_bytes_sent = 0

        while True:
            iteration += 1
            logger.debug(f"Event loop iteration {iteration}", module="mtr.ssh")

            r, w, x = select.select([channel, sys.stdin], [], [])
            logger.debug(f"Select returned: {len(r)} readable, {len(w)} writable, {len(x)} exceptional", module="mtr.ssh")

            if channel in r:
                logger.debug("Channel is readable", module="mtr.ssh")
                try:
                    data = channel.recv(BUFFER_SIZE)
                    bytes_received = len(data)
                    total_bytes_received += bytes_received

                    if bytes_received == 0:
                        logger.debug("Channel received EOF (0 bytes)", module="mtr.ssh")
                        break

                    logger.debug(
                        f"Received {bytes_received} bytes from channel (total: {total_bytes_received})", module="mtr.ssh"
                    )
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                except socket.error as e:
                    logger.debug(f"Socket error (EAGAIN/EWOULDBLOCK): {e}", module="mtr.ssh")
                except Exception as e:
                    logger.warning(f"Error receiving data from channel: {e}", module="mtr.ssh")

            if sys.stdin in r:
                logger.debug("Stdin is readable", module="mtr.ssh")
                try:
                    data = os.read(sys.stdin.fileno(), BUFFER_SIZE)
                    bytes_sent = len(data)
                    total_bytes_sent += bytes_sent

                    if bytes_sent == 0:
                        logger.debug("Stdin received EOF (0 bytes)", module="mtr.ssh")
                        break

                    logger.debug(f"Read {bytes_sent} bytes from stdin (total: {total_bytes_sent})", module="mtr.ssh")
                    channel.send(data)
                    logger.debug(f"Sent {bytes_sent} bytes to channel", module="mtr.ssh")
                except Exception as e:
                    logger.warning(f"Error reading from stdin: {e}", module="mtr.ssh")

        logger.debug(f"Event loop ended after {iteration} iterations", module="mtr.ssh")
        logger.debug(f"Total bytes received: {total_bytes_received}, sent: {total_bytes_sent}", module="mtr.ssh")

        logger.debug("Waiting for exit status (timeout=5.0)", module="mtr.ssh")
        try:
            channel.settimeout(5.0)
            exit_code = channel.recv_exit_status()
            logger.debug(f"Received exit status: {exit_code}", module="mtr.ssh")
            return exit_code
        except socket.timeout:
            logger.warning("Timeout waiting for exit status, assuming failure", module="mtr.ssh")
            return -1

    def _cleanup_resources(self, channel, old_tty_attrs, old_handler):
        """Cleanup resources with proper error handling."""
        logger.debug("Starting cleanup", module="mtr.ssh")

        logger.debug("Restoring terminal settings", module="mtr.ssh")
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty_attrs)
            logger.debug("Terminal settings restored successfully", module="mtr.ssh")
        except Exception as e:
            logger.warning(f"Failed to restore terminal settings: {e}", module="mtr.ssh")

        logger.debug("Restoring signal handler", module="mtr.ssh")
        try:
            signal.signal(signal.SIGWINCH, old_handler)
            logger.debug("Signal handler restored successfully", module="mtr.ssh")
        except Exception as e:
            logger.warning(f"Failed to restore signal handler: {e}", module="mtr.ssh")

        logger.debug("Closing channel", module="mtr.ssh")
        try:
            if channel:
                channel.close()
                logger.debug("Channel closed successfully", module="mtr.ssh")
        except Exception as e:
            logger.debug(f"Error closing channel: {e}", module="mtr.ssh")

        logger.info("Cleanup completed", module="mtr.ssh")

    def run_interactive_shell(self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None) -> int:
        """
        Runs an interactive shell with PTY support.
        Handles full TTY raw mode, window resizing, and socket forwarding.
        Returns exit code.
        """
        logger.info(f"Starting interactive shell for command: {command}", module="mtr.ssh")
        logger.debug(f"Workdir: {workdir}, Pre-cmd: {pre_cmd}", module="mtr.ssh")

        if not self.client:
            raise SSHError("Client not connected")

        if not HAS_TTY:
            raise SSHError("Interactive mode not supported on this platform (missing termios).")

        logger.debug(f"HAS_TTY: {HAS_TTY}", module="mtr.ssh")
        logger.debug(f"Current thread is main: {threading.current_thread() is threading.main_thread()}", module="mtr.ssh")

        if threading.current_thread() is not threading.main_thread():
            raise SSHError("Interactive shell must run in main thread")

        logger.debug("Setting up SSH channel with PTY", module="mtr.ssh")
        channel = self._setup_channel(command, workdir, pre_cmd)
        logger.info("PTY allocated successfully", module="mtr.ssh")

        def _resize_handler(signum, frame):
            logger.debug(f"SIGWINCH received (signal {signum})", module="mtr.ssh")
            try:
                if channel and channel.active:
                    c, r = os.get_terminal_size()
                    logger.debug(f"Resizing PTY to {c}x{r}", module="mtr.ssh")
                    channel.resize_pty(width=c, height=r)
                    logger.debug("PTY resize completed", module="mtr.ssh")
                else:
                    logger.debug("Channel not active, skipping resize", module="mtr.ssh")
            except OSError as e:
                logger.debug(f"Failed to resize terminal: {e}", module="mtr.ssh")
            except Exception as e:
                logger.debug(f"Unexpected error in resize handler: {e}", module="mtr.ssh")

        logger.debug("Saving terminal attributes", module="mtr.ssh")
        old_tty_attrs = termios.tcgetattr(sys.stdin)

        logger.debug("Registering SIGWINCH handler", module="mtr.ssh")
        old_handler = signal.signal(signal.SIGWINCH, _resize_handler)

        logger.debug("Entering raw mode", module="mtr.ssh")
        tty.setraw(sys.stdin.fileno())

        try:
            logger.debug("Starting event loop", module="mtr.ssh")
            exit_code = self._run_event_loop(channel)
            logger.info(f"Interactive shell exited with code: {exit_code}", module="mtr.ssh")
            return exit_code
        finally:
            self._cleanup_resources(channel, old_tty_attrs, old_handler)

    def close(self):
        if self.client:
            logger.debug("Closing SSH connection", module="mtr.ssh")
            self.client.close()
            logger.debug("SSH connection closed", module="mtr.ssh")
