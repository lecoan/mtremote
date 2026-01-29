import fnmatch
import os
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import List, Optional

import paramiko


class SyncError(Exception):
    pass


class BaseSyncer(ABC):
    def __init__(self, local_dir: str, remote_dir: str, exclude: List[str]):
        self.local_dir = local_dir
        self.remote_dir = remote_dir
        self.exclude = exclude

    @abstractmethod
    def sync(self):
        pass


class SftpSyncer(BaseSyncer):
    def __init__(
        self,
        local_dir: str,
        remote_dir: str,
        host: str,
        user: str,
        key_filename: Optional[str] = None,
        password: Optional[str] = None,
        port: int = 22,
        exclude: List[str] = None,
    ):
        super().__init__(local_dir, remote_dir, exclude or [])
        self.host = host
        self.user = user
        self.key_filename = key_filename
        self.password = password
        self.port = port
        self.transport = None
        self.sftp = None

    def _should_ignore(self, filename: str) -> bool:
        for pattern in self.exclude:
            # Handle directory exclusion (basic)
            if pattern.endswith("/") and filename.startswith(pattern.rstrip("/")):
                return True
            if fnmatch.fnmatch(filename, pattern):
                return True
        return False

    def _connect(self):
        try:
            self.transport = paramiko.Transport((self.host, self.port))
            connect_kwargs = {"username": self.user}

            if self.key_filename:
                key_path = os.path.expanduser(self.key_filename)
                # Try different key types? For now assuming RSA or standard loading
                # Or just use connect method of SSHClient? No, Sftp is lower level usually,
                # but we can use SSHClient to get sftp

                # Simpler approach: Use SSHClientWrapper logic or just Paramiko SSHClient
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                k_kwargs = {
                    "hostname": self.host,
                    "username": self.user,
                    "port": self.port,
                    "key_filename": key_path,
                }
                if self.password:
                    k_kwargs["password"] = self.password

                client.connect(**k_kwargs)
                self.sftp = client.open_sftp()
                return

            if self.password:
                connect_kwargs["password"] = self.password
                self.transport.connect(**connect_kwargs)
                self.sftp = paramiko.SFTPClient.from_transport(self.transport)
            else:
                raise SyncError("No auth method provided (need key or password)")

        except Exception as e:
            raise SyncError(f"SFTP Connection failed: {e}")

    def _ensure_remote_dir(self, remote_path: str):
        """Recursively create remote directory."""
        # This is a bit expensive, optimization: assume parent exists or try/except
        # Simple implementation:
        dirs = remote_path.split("/")
        current = ""
        for d in dirs:
            if not d:
                continue
            current += f"/{d}"
            try:
                self.sftp.stat(current)
            except FileNotFoundError:
                try:
                    self.sftp.mkdir(current)
                except OSError:
                    pass  # Already exists maybe

    def sync(self):
        if not self.sftp:
            self._connect()

        # Ensure base remote dir exists
        try:
            self.sftp.stat(self.remote_dir)
        except FileNotFoundError:
            self._ensure_remote_dir(self.remote_dir)

        # Walk local tree
        for root, dirs, files in os.walk(self.local_dir):
            # Filtering dirs in place to prevent recursion
            dirs[:] = [d for d in dirs if not self._should_ignore(d)]

            rel_path = os.path.relpath(root, self.local_dir)
            if rel_path == ".":
                remote_root = self.remote_dir
            else:
                remote_root = os.path.join(self.remote_dir, rel_path)

                # Check/Create remote dir
                try:
                    self.sftp.stat(remote_root)
                except FileNotFoundError:
                    self.sftp.mkdir(remote_root)

            for file in files:
                if self._should_ignore(file):
                    continue

                local_file = os.path.join(root, file)
                remote_file = os.path.join(remote_root, file)

                # Check sync necessity (Size & Mtime)
                should_upload = True
                try:
                    remote_stat = self.sftp.stat(remote_file)
                    local_stat = os.stat(local_file)

                    if remote_stat.st_size == local_stat.st_size and int(remote_stat.st_mtime) >= int(local_stat.st_mtime):
                        should_upload = False
                except FileNotFoundError:
                    pass  # Does not exist, must upload

                if should_upload:
                    # print(f"Uploading {local_file} -> {remote_file}")
                    self.sftp.put(local_file, remote_file)
                    # Preserve permissions
                    mode = os.stat(local_file).st_mode
                    self.sftp.chmod(remote_file, mode)

        if self.sftp:
            self.sftp.close()
        if self.transport:
            self.transport.close()

    def download(self, remote_path: str, local_path: str):
        """Download file or directory from remote to local."""
        if not self.sftp:
            self._connect()

        try:
            # Ensure local directory exists
            local_dir = os.path.dirname(local_path)
            if local_dir and not os.path.exists(local_dir):
                os.makedirs(local_dir, exist_ok=True)

            try:
                import stat

                remote_stat = self.sftp.stat(remote_path)
                is_dir = stat.S_ISDIR(remote_stat.st_mode)

                if is_dir:
                    self._download_dir(remote_path, local_path)
                else:
                    self._download_file(remote_path, local_path)
            except FileNotFoundError:
                raise SyncError(f"Remote path not found: {remote_path}")
            except Exception as e:
                raise SyncError(f"Download failed: {e}")
        finally:
            if self.sftp:
                self.sftp.close()
            if self.transport:
                self.transport.close()

    def _should_download_file(self, remote_file: str, local_file: str) -> bool:
        """Check if file should be downloaded based on size and mtime."""
        try:
            remote_stat = self.sftp.stat(remote_file)
            local_stat = os.stat(local_file)

            # Size different, need download
            if remote_stat.st_size != local_stat.st_size:
                return True

            # Remote file is newer than local file
            return int(remote_stat.st_mtime) > int(local_stat.st_mtime)
        except FileNotFoundError:
            return True  # Local file doesn't exist, must download

    def _download_file(self, remote_file: str, local_file: str):
        """Download a single file with incremental check."""
        if not self._should_download_file(remote_file, local_file):
            return  # No need to download

        self.sftp.get(remote_file, local_file)
        # Preserve permissions
        remote_stat = self.sftp.stat(remote_file)
        os.chmod(local_file, remote_stat.st_mode)

    def _download_dir(self, remote_dir: str, local_dir: str):
        """Recursively download a directory."""
        if not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        for entry in self.sftp.listdir_attr(remote_dir):
            remote_path = f"{remote_dir}/{entry.filename}"
            local_path = os.path.join(local_dir, entry.filename)

            if self._should_ignore(entry.filename):
                continue

            import stat

            if stat.S_ISDIR(entry.st_mode):
                self._download_dir(remote_path, local_path)
            else:
                self._download_file(remote_path, local_path)


class RsyncSyncer(BaseSyncer):
    def __init__(
        self,
        local_dir: str,
        remote_dir: str,
        host: str,
        user: str,
        key_filename: Optional[str] = None,
        password: Optional[str] = None,
        port: int = 22,
        exclude: List[str] = None,
    ):
        super().__init__(local_dir, remote_dir, exclude or [])
        self.host = host
        self.user = user
        self.key_filename = key_filename
        self.password = password
        self.port = port

    def _build_ssh_options(self) -> str:
        """Build SSH options string for rsync."""
        opts = f"ssh -p {self.port}"
        if self.key_filename:
            opts += f" -i {self.key_filename}"
        return opts

    def _build_rsync_base(self) -> List[str]:
        """Build rsync base command with common options."""
        cmd = ["rsync", "-azq"]

        # Add excludes
        for item in self.exclude:
            cmd.append(f"--exclude={item}")

        # SSH options
        cmd.extend(["-e", self._build_ssh_options()])

        return cmd

    def _wrap_with_sshpass(self, cmd: List[str]) -> List[str]:
        """Wrap command with sshpass if password authentication is used."""
        if self.password and not self.key_filename:
            return ["sshpass", "-p", self.password] + cmd
        return cmd

    def _check_sshpass(self):
        """Check if sshpass is available when password authentication is used."""
        if self.password and not self.key_filename:
            if not shutil.which("sshpass"):
                raise SyncError("Rsync with password requires 'sshpass'. Please install it or use SSH Key.")

    def _build_rsync_command(self) -> List[str]:
        """Build rsync command for uploading (local -> remote)."""
        # Ensure local dir ends with / to sync contents, not the dir itself
        src = self.local_dir if self.local_dir.endswith("/") else f"{self.local_dir}/"
        dest = f"{self.user}@{self.host}:{shlex.quote(self.remote_dir)}"

        cmd = self._build_rsync_base()
        cmd.extend([src, dest])

        return self._wrap_with_sshpass(cmd)

    def _build_rsync_download_command(self, remote_path: str, local_path: str) -> List[str]:
        """Build rsync command for downloading (remote -> local)."""
        src = f"{self.user}@{self.host}:{shlex.quote(remote_path)}"

        cmd = self._build_rsync_base()
        cmd.extend([src, local_path])

        return self._wrap_with_sshpass(cmd)

    def sync(self):
        self._check_sshpass()
        cmd = self._build_rsync_command()
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise SyncError(f"Rsync failed with exit code {e.returncode}")

    def download(self, remote_path: str, local_path: str):
        """Download file or directory from remote to local."""
        self._check_sshpass()

        # Ensure local parent directory exists
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        cmd = self._build_rsync_download_command(remote_path, local_path)
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise SyncError(f"Rsync download failed with exit code {e.returncode}")
