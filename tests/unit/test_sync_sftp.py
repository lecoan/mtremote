import os
import stat
from unittest.mock import MagicMock, patch

import pytest

from mtr.sync import SftpSyncer, SyncError


@pytest.fixture
def mock_sftp_syncer():
    """Create a SftpSyncer with mocked SFTP connection."""
    syncer = SftpSyncer(
        local_dir="/local/project",
        remote_dir="/remote/project",
        host="192.168.1.1",
        user="dev",
        password="password",
        exclude=[".git", "__pycache__"],
        respect_gitignore=False,
    )
    return syncer


def test_sftp_download_file(mocker, mock_sftp_syncer):
    """Test downloading a single file."""
    # Mock SFTP connection
    mock_sftp = MagicMock()
    mock_sftp_syncer.sftp = mock_sftp

    # Mock stat for remote file (regular file)
    mock_stat = MagicMock()
    mock_stat.st_mode = stat.S_IFREG | 0o644
    mock_stat.st_mtime = 1234567890
    mock_stat.st_size = 1024
    mock_sftp.stat.return_value = mock_stat

    # Mock local file stat (file doesn't exist)
    mocker.patch("os.stat", side_effect=FileNotFoundError())
    mocker.patch("os.chmod")

    # Mock get method
    mock_sftp.get = MagicMock()

    # Perform download
    mock_sftp_syncer._download_file("/remote/file.txt", "/local/file.txt")

    # Verify get was called
    mock_sftp.get.assert_called_once_with("/remote/file.txt", "/local/file.txt")
    os.chmod.assert_called_once_with("/local/file.txt", mock_stat.st_mode)


def test_sftp_download_file_incremental(mocker, mock_sftp_syncer):
    """Test that download is skipped when local file is up to date."""
    # Mock SFTP connection
    mock_sftp = MagicMock()
    mock_sftp_syncer.sftp = mock_sftp

    # Mock stat for remote file
    remote_stat = MagicMock()
    remote_stat.st_mode = stat.S_IFREG | 0o644
    remote_stat.st_mtime = 1000
    remote_stat.st_size = 1024
    mock_sftp.stat.return_value = remote_stat

    # Mock local file stat (same size, newer mtime)
    local_stat = MagicMock()
    local_stat.st_mtime = 2000
    local_stat.st_size = 1024
    mocker.patch("os.stat", return_value=local_stat)

    # Mock get method
    mock_sftp.get = MagicMock()

    # Perform download
    mock_sftp_syncer._download_file("/remote/file.txt", "/local/file.txt")

    # Verify get was NOT called (file is up to date)
    mock_sftp.get.assert_not_called()


def test_sftp_download_file_force_when_different(mocker, mock_sftp_syncer):
    """Test that download happens when files are different."""
    # Mock SFTP connection
    mock_sftp = MagicMock()
    mock_sftp_syncer.sftp = mock_sftp

    # Mock stat for remote file
    remote_stat = MagicMock()
    remote_stat.st_mode = stat.S_IFREG | 0o644
    remote_stat.st_mtime = 2000
    remote_stat.st_size = 2048  # Different size
    mock_sftp.stat.return_value = remote_stat

    # Mock local file stat
    local_stat = MagicMock()
    local_stat.st_mtime = 1000
    local_stat.st_size = 1024
    mocker.patch("os.stat", return_value=local_stat)
    mocker.patch("os.chmod")

    # Mock get method
    mock_sftp.get = MagicMock()

    # Perform download
    mock_sftp_syncer._download_file("/remote/file.txt", "/local/file.txt")

    # Verify get was called (file is different)
    mock_sftp.get.assert_called_once()


def test_sftp_download_remote_not_found(mocker, mock_sftp_syncer):
    """Test error raised when remote path doesn't exist."""
    # Mock SFTP connection
    mock_sftp = MagicMock()
    mock_sftp_syncer.sftp = mock_sftp

    # Mock stat to raise FileNotFoundError
    mock_sftp.stat.side_effect = FileNotFoundError()

    # Mock local directory operations
    mocker.patch("os.path.dirname", return_value="/local")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.makedirs")

    with pytest.raises(SyncError, match="Remote path not found"):
        mock_sftp_syncer.download("/remote/nonexistent.txt", "/local/file.txt")


def test_sftp_download_connection_closed(mocker, mock_sftp_syncer):
    """Test that connection is closed after download."""
    # Mock SFTP connection
    mock_sftp = MagicMock()
    mock_transport = MagicMock()
    mock_sftp_syncer.sftp = mock_sftp
    mock_sftp_syncer.transport = mock_transport

    # Mock stat for remote file
    mock_stat = MagicMock()
    mock_stat.st_mode = stat.S_IFREG | 0o644
    mock_sftp.stat.return_value = mock_stat

    # Mock local operations
    mocker.patch("os.path.dirname", return_value="/local")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.makedirs")
    mocker.patch("os.stat", side_effect=FileNotFoundError())
    mocker.patch("os.chmod")

    # Perform download
    mock_sftp_syncer.download("/remote/file.txt", "/local/file.txt")

    # Verify connection was closed
    mock_sftp.close.assert_called_once()
    mock_transport.close.assert_called_once()


def test_sftp_download_connection_closed_on_error(mocker, mock_sftp_syncer):
    """Test that connection is closed even when download fails."""
    # Mock SFTP connection
    mock_sftp = MagicMock()
    mock_transport = MagicMock()
    mock_sftp_syncer.sftp = mock_sftp
    mock_sftp_syncer.transport = mock_transport

    # Mock stat to raise error
    mock_sftp.stat.side_effect = Exception("Connection error")

    # Mock local directory operations
    mocker.patch("os.path.dirname", return_value="/local")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.makedirs")

    with pytest.raises(SyncError):
        mock_sftp_syncer.download("/remote/file.txt", "/local/file.txt")

    # Verify connection was still closed
    mock_sftp.close.assert_called_once()
    mock_transport.close.assert_called_once()


def test_sftp_respect_gitignore_true_raises_error():
    """Test that SftpSyncer raises error when respect_gitignore is True."""
    with pytest.raises(SyncError, match="respect_gitignore is not supported in SFTP mode"):
        SftpSyncer(
            local_dir="/local/project",
            remote_dir="/remote/project",
            host="192.168.1.1",
            user="dev",
            password="password",
            respect_gitignore=True,
        )


def test_sftp_respect_gitignore_false_works():
    """Test that SftpSyncer works when respect_gitignore is False."""
    # This should not raise an error
    syncer = SftpSyncer(
        local_dir="/local/project",
        remote_dir="/remote/project",
        host="192.168.1.1",
        user="dev",
        password="password",
        respect_gitignore=False,
    )
    assert syncer.respect_gitignore is False
