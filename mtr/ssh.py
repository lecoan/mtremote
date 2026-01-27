import paramiko
import os
from typing import Optional, Generator, Tuple


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

    def exec_command_stream(
        self, command: str, workdir: Optional[str] = None, pre_cmd: Optional[str] = None
    ) -> Generator[str, None, int]:
        """
        Executes command and yields output lines.
        Returns the exit code.
        """
        if not self.client:
            raise SSHError("Client not connected")

        full_command = command

        parts = []
        if workdir:
            parts.append(f"cd {workdir}")
        if pre_cmd:
            parts.append(pre_cmd)
        parts.append(command)

        full_command = " && ".join(parts)

        try:
            # get_pty=True merges stderr into stdout
            stdin, stdout, stderr = self.client.exec_command(full_command, get_pty=True)

            # Close stdin as we don't use it for now (interactive input later?)
            stdin.close()

            # Stream output
            for line in stdout:
                yield line

            # Wait for command to finish and get exit code
            exit_code = stdout.channel.recv_exit_status()
            return exit_code

        except paramiko.SSHException as e:
            raise SSHError(f"Command execution failed: {e}")

    def close(self):
        if self.client:
            self.client.close()
