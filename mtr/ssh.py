import paramiko
import os
import sys
import select
import socket
from typing import Optional, Generator, Tuple

# Try to import termios/tty for interactive shell
try:
    import termios
    import tty
    import signal
    import fcntl
    import struct

    HAS_TTY = True
except ImportError:
    HAS_TTY = False


class SSHError(Exception):
    pass


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

    def _build_command(
        self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None
    ) -> str:
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
            # For simplicity in this generator, we only yield stdout if pty=False to avoid interleaving complexity in batch mode,
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

    def run_interactive_shell(
        self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None
    ) -> int:
        """
        Runs an interactive shell with PTY support.
        Handles full TTY raw mode, window resizing, and socket forwarding.
        Returns exit code.
        """
        if not self.client:
            raise SSHError("Client not connected")

        if not HAS_TTY:
            raise SSHError(
                "Interactive mode not supported on this platform (missing termios)."
            )

        full_command = self._build_command(command, workdir, pre_cmd)

        # Open a new channel
        transport = self.client.get_transport()
        if not transport:
            raise SSHError("Transport not active")

        channel = transport.open_session()

        # Get terminal size
        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            cols, rows = 80, 24

        channel.get_pty(term=os.environ.get("TERM", "vt100"), width=cols, height=rows)
        channel.exec_command(full_command)

        # Setup window resize handler
        def _resize_handler(signum, frame):
            try:
                c, r = os.get_terminal_size()
                channel.resize_pty(width=c, height=r)
            except:
                pass

        old_handler = signal.signal(signal.SIGWINCH, _resize_handler)

        # Enter raw mode
        old_tty_attrs = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin.fileno())

        try:
            channel.settimeout(0.0)

            while True:
                r, w, x = select.select([channel, sys.stdin], [], [])

                if channel in r:
                    try:
                        data = channel.recv(1024)
                        if len(data) == 0:
                            break
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                    except socket.timeout:
                        pass

                if sys.stdin in r:
                    data = os.read(sys.stdin.fileno(), 1024)
                    if len(data) == 0:
                        break
                    channel.send(data)

            # Wait for exit status
            # We need to block until it's closed?
            # Usually recv returning 0 means EOF.

            # channel.recv_exit_status() might block if we are not careful
            # But since EOF is received, it should be ready.
            exit_code = channel.recv_exit_status()
            return exit_code

        finally:
            # Restore terminal settings
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty_attrs)
            signal.signal(signal.SIGWINCH, old_handler)
            channel.close()

    def close(self):
        if self.client:
            self.client.close()
