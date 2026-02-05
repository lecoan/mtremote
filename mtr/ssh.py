"""SSH utilities for MTRemote."""

import os
import shutil
import subprocess
from typing import Optional

from mtr.logger import get_logger


class SSHError(Exception):
    """SSH-related errors."""

    pass


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


def _build_command(command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None) -> str:
    """Build the full command string with workdir and pre_cmd."""
    parts = []
    if workdir:
        parts.append(f"cd {workdir}")
    if pre_cmd:
        parts.append(pre_cmd)
    parts.append(command)
    return " && ".join(parts)


def run_ssh_command(
    host: str,
    user: str,
    command: str,
    port: int = 22,
    key_filename: Optional[str] = None,
    password: Optional[str] = None,
    workdir: Optional[str] = None,
    pre_cmd: Optional[str] = None,
    tty: bool = True,
) -> int:
    """
    Run a command on remote host via system SSH.

    Args:
        host: Remote host address
        user: SSH username
        command: Command to execute
        port: SSH port (default: 22)
        key_filename: Path to SSH private key
        password: SSH password (requires sshpass)
        workdir: Working directory on remote host
        pre_cmd: Command to run before main command
        tty: If True, use ssh -t for TTY allocation

    Returns:
        Exit code from the remote command

    Raises:
        SSHError: If SSH command fails or is not available
    """
    logger = get_logger()
    mode_str = "interactive" if tty else "batch"
    logger.info(f"Executing {mode_str} command via SSH: {command}", module="mtr.ssh")
    logger.debug(f"Host: {host}, User: {user}, Port: {port}, TTY: {tty}", module="mtr.ssh")

    # Check SSH availability
    _check_ssh_availability()

    # Check sshpass availability if password is used
    if password and not key_filename:
        _check_sshpass_availability()

    # Build the full command
    full_command = _build_command(command, workdir, pre_cmd)
    logger.debug(f"Full command: {full_command}", module="mtr.ssh")

    # Build SSH command
    ssh_cmd = ["ssh"]

    # Add -t flag for TTY mode
    if tty:
        ssh_cmd.append("-t")

    # Port
    if port != 22:
        ssh_cmd.extend(["-p", str(port)])

    # Key authentication
    if key_filename:
        ssh_cmd.extend(["-i", os.path.expanduser(key_filename)])

    # Target host and command
    target = f"{user}@{host}"
    ssh_cmd.extend([target, full_command])

    # Wrap with sshpass if password is provided
    if password and not key_filename:
        ssh_cmd = ["sshpass", "-p", password] + ssh_cmd

    logger.debug(f"Executing: {' '.join(ssh_cmd)}", module="mtr.ssh")

    # Run command
    try:
        result = subprocess.run(ssh_cmd)
        logger.info(f"Command exited with code: {result.returncode}", module="mtr.ssh")
        return result.returncode
    except FileNotFoundError as e:
        logger.error(f"Command not found: {e}", module="mtr.ssh")
        raise SSHError(f"SSH command execution failed: {e}")
    except Exception as e:
        logger.error(f"SSH command failed: {e}", module="mtr.ssh")
        raise SSHError(f"SSH command failed: {e}")
