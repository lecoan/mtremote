import os
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import List, Optional


class SyncError(Exception):
    pass


class BaseSyncer(ABC):
    def __init__(self, local_dir: str, remote_dir: str, exclude: List[str], respect_gitignore: bool = True):
        self.local_dir = local_dir
        self.remote_dir = remote_dir
        self.exclude = exclude
        self.respect_gitignore = respect_gitignore

    @abstractmethod
    def sync(self, show_progress: bool = False, progress_callback=None):
        pass


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
        respect_gitignore: bool = True,
    ):
        super().__init__(local_dir, remote_dir, exclude or [], respect_gitignore)
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

    def _build_rsync_base(self, show_progress: bool = False) -> List[str]:
        """Build rsync base command with common options."""
        if show_progress:
            # In progress mode, use -av --info=NAME to show filenames only
            cmd = ["rsync", "-av", "--info=NAME"]
        else:
            # Silent mode
            cmd = ["rsync", "-azq"]

        # Add gitignore filter if enabled
        if self.respect_gitignore:
            gitignore_path = os.path.join(self.local_dir, ".gitignore")
            if os.path.exists(gitignore_path):
                cmd.append("--filter=:- .gitignore")

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

    def _check_rsync_version(self) -> tuple:
        """Check local rsync version and return (major, minor, patch) tuple.

        Returns:
            Tuple of (major, minor, patch) version numbers
        Raises:
            SyncError: If rsync is not installed or version cannot be parsed
        """
        try:
            result = subprocess.run(["rsync", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise SyncError("Failed to check rsync version. Is rsync installed?")

            # Parse version from first line, e.g., "rsync  version 3.2.5  protocol version 31"
            first_line = result.stdout.split("\n")[0]
            import re

            match = re.search(r"version\s+(\d+)\.(\d+)\.(\d+)", first_line)
            if not match:
                # Try alternative format: "rsync version 2.6.9 compatible"
                match = re.search(r"version\s+(\d+)\.(\d+)\.(\d+)", first_line)
                if not match:
                    raise SyncError(f"Cannot parse rsync version from: {first_line}")

            major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return (major, minor, patch)
        except FileNotFoundError:
            raise SyncError("rsync not found. Please install rsync.")
        except subprocess.TimeoutExpired:
            raise SyncError("Timeout while checking rsync version.")
        except Exception as e:
            raise SyncError(f"Failed to check rsync version: {e}")

    def _is_rsync_version_supported(self, min_version: tuple = (3, 1, 0)) -> bool:
        """Check if local rsync version meets minimum requirement.

        Args:
            min_version: Minimum required version as (major, minor, patch) tuple
        Returns:
            True if version is supported, False otherwise
        """
        try:
            current_version = self._check_rsync_version()
            return current_version >= min_version
        except SyncError:
            return False

    def _build_rsync_command(self, show_progress: bool = False) -> List[str]:
        """Build rsync command for uploading (local -> remote)."""
        # Ensure local dir ends with / to sync contents, not the dir itself
        src = self.local_dir if self.local_dir.endswith("/") else f"{self.local_dir}/"
        dest = f"{self.user}@{self.host}:{shlex.quote(self.remote_dir)}"

        cmd = self._build_rsync_base(show_progress=show_progress)
        cmd.extend([src, dest])

        return self._wrap_with_sshpass(cmd)

    def _build_rsync_download_command(self, remote_path: str, local_path: str, show_progress: bool = False) -> List[str]:
        """Build rsync command for downloading (remote -> local)."""
        src = f"{self.user}@{self.host}:{shlex.quote(remote_path)}"

        cmd = self._build_rsync_base(show_progress=show_progress)
        cmd.extend([src, local_path])

        return self._wrap_with_sshpass(cmd)

    def sync(self, show_progress: bool = False, progress_callback=None):
        self._check_sshpass()

        # Check rsync version if progress mode is requested
        if show_progress and progress_callback:
            if not self._is_rsync_version_supported():
                version = self._check_rsync_version()
                raise SyncError(
                    f"rsync version {version[0]}.{version[1]}.{version[2]} is too old. "
                    f"Progress display requires rsync >= 3.1.0. "
                    f"Please upgrade rsync or use --no-tty mode."
                )

        cmd = self._build_rsync_command(show_progress=show_progress)

        try:
            if show_progress and progress_callback:
                # Run with real-time output parsing for progress display
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True
                )

                # Parse rsync output line by line
                for line in process.stdout:
                    line = line.strip()
                    # Skip empty lines and summary lines
                    if line and not line.startswith("sent") and not line.startswith("total"):
                        # Extract filename from rsync output
                        # Rsync --info=NAME outputs filenames directly
                        if not line.startswith("receiving") and not line.startswith("building"):
                            progress_callback(line)

                process.wait()
                if process.returncode != 0:
                    raise SyncError(f"Rsync failed with exit code {process.returncode}")
            else:
                # Silent mode - use subprocess.run
                subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise SyncError(f"Rsync failed with exit code {e.returncode}")

    def download(self, remote_path: str, local_path: str, show_progress: bool = False, progress_callback=None):
        """Download file or directory from remote to local."""
        self._check_sshpass()

        # Ensure local parent directory exists
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        cmd = self._build_rsync_download_command(remote_path, local_path, show_progress=show_progress)
        try:
            if show_progress and progress_callback:
                # Run with real-time output parsing for progress display
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True
                )

                # Parse rsync output line by line
                for line in process.stdout:
                    line = line.strip()
                    # Skip empty lines and summary lines
                    if line and not line.startswith("sent") and not line.startswith("total"):
                        # Extract filename from rsync output
                        # Rsync --info=NAME outputs filenames directly
                        if not line.startswith("receiving") and not line.startswith("building"):
                            progress_callback(line)

                process.wait()
                if process.returncode != 0:
                    raise SyncError(f"Rsync download failed with exit code {process.returncode}")
            else:
                # Silent mode - use subprocess.run
                subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise SyncError(f"Rsync download failed with exit code {e.returncode}")
