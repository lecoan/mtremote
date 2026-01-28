import os
import shutil
import subprocess
from typing import Generator, Optional

import paramiko

from mtr.logger import get_logger


class SSHError(Exception):
    pass


# Constants for batch mode
BUFFER_SIZE = 32768  # 32KB for better performance


def _check_ssh_availability():
    """Check if ssh command is available."""
    if shutil.which("ssh") is None:
        raise SSHError(
            "SSH command not found. Please install OpenSSH client.\n"
            "  macOS: brew install openssh\n"
            "  Ubuntu/Debian: sudo apt-get install openssh-client\n"
            "  CentOS/RHEL: sudo yum install openssh-clients"
        )


def _check_sshpass_availability():
    """Check if sshpass command is available."""
    if shutil.which("sshpass") is None:
        raise SSHError(
            "sshpass command not found. Please install sshpass for password authentication.\n"
            "  macOS: brew install hudochenkov/sshpass/sshpass\n"
            "  Ubuntu/Debian: sudo apt-get install sshpass\n"
            "  CentOS/RHEL: sudo yum install sshpass"
        )


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
        logger = get_logger()
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
        logger = get_logger()
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

    def run_interactive_shell(self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None) -> int:
        """
        Runs an interactive shell using system ssh -t command.
        This provides full TTY support with proper signal handling.
        Returns exit code.
        """
        logger = get_logger()
        logger.info(f"Starting interactive shell via ssh -t: {command}", module="mtr.ssh")
        logger.debug(f"Workdir: {workdir}, Pre-cmd: {pre_cmd}", module="mtr.ssh")

        # Check SSH availability
        _check_ssh_availability()

        # Check sshpass availability if password is used
        if self.password:
            _check_sshpass_availability()

        full_command = self._build_command(command, workdir, pre_cmd)

        # Build ssh command
        ssh_cmd = ["ssh", "-t"]

        # Port
        if self.port != 22:
            ssh_cmd.extend(["-p", str(self.port)])

        # Key authentication
        if self.key_filename:
            ssh_cmd.extend(["-i", os.path.expanduser(self.key_filename)])

        # Target host and command
        target = f"{self.user}@{self.host}"
        ssh_cmd.extend([target, full_command])

        # Wrap with sshpass if password is provided
        if self.password:
            ssh_cmd = ["sshpass", "-p", self.password] + ssh_cmd

        logger.debug(f"Executing: {' '.join(ssh_cmd)}", module="mtr.ssh")

        # Run command with direct stdin/stdout/stderr forwarding
        try:
            result = subprocess.run(ssh_cmd)
            logger.info(f"Interactive shell exited with code: {result.returncode}", module="mtr.ssh")
            return result.returncode
        except FileNotFoundError as e:
            # This shouldn't happen if _check_ssh_availability passed, but just in case
            logger.error(f"Command not found: {e}", module="mtr.ssh")
            raise SSHError(f"SSH command execution failed: {e}")
        except Exception as e:
            logger.error(f"Interactive shell failed: {e}", module="mtr.ssh")
            raise SSHError(f"Interactive shell failed: {e}")

    def close(self):
        if self.client:
            logger = get_logger()
            logger.debug("Closing SSH connection", module="mtr.ssh")
            self.client.close()
            logger.debug("SSH connection closed", module="mtr.ssh")
