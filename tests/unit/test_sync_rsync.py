import pytest

from mtr.sync import RsyncSyncer, SyncError


def test_rsync_command_generation():
    syncer = RsyncSyncer(
        local_dir="/local/project",
        remote_dir="/remote/project",
        host="192.168.1.1",
        user="dev",
        key_filename="~/.ssh/id_rsa",
        exclude=[".git", "__pycache__"],
    )

    cmd_list = syncer._build_rsync_command()
    # cmd_str = " ".join(cmd_list)

    assert "rsync" in cmd_list[0]
    # Check for archive mode (silent mode uses -azq)
    assert "-azq" in cmd_list or any(x.startswith("-") and "a" in x and "q" in x for x in cmd_list)

    # Check exclude
    assert "--exclude=.git" in cmd_list
    assert "--exclude=__pycache__" in cmd_list

    # Check source (ensure trailing slash for rsync content sync)
    assert "/local/project/" in cmd_list

    # Check dest
    assert "dev@192.168.1.1:/remote/project" in cmd_list

    # Check SSH args
    assert "-e" in cmd_list
    # Find the element after -e
    e_index = cmd_list.index("-e")
    ssh_cmd = cmd_list[e_index + 1]
    assert "ssh" in ssh_cmd
    assert "-i ~/.ssh/id_rsa" in ssh_cmd


def test_rsync_command_generation_with_progress():
    """Test rsync command generation in progress mode."""
    syncer = RsyncSyncer(
        local_dir="/local/project",
        remote_dir="/remote/project",
        host="192.168.1.1",
        user="dev",
        key_filename="~/.ssh/id_rsa",
        exclude=[".git", "__pycache__"],
    )

    cmd_list = syncer._build_rsync_command(show_progress=True)

    assert "rsync" in cmd_list[0]
    # Check for archive mode with verbose (progress mode uses -av --info=NAME)
    assert "-av" in cmd_list or any(x.startswith("-") and "a" in x and "v" in x for x in cmd_list)
    assert "--info=NAME" in cmd_list

    # Check that -q (quiet) is NOT in progress mode
    assert "-azq" not in cmd_list
    assert not any(x.startswith("-") and "q" in x for x in cmd_list)

    # Check exclude
    assert "--exclude=.git" in cmd_list
    assert "--exclude=__pycache__" in cmd_list


def test_rsync_with_sshpass(mocker):
    """Test sshpass command generation when password is used."""
    mocker.patch("shutil.which", return_value="/usr/bin/sshpass")

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
        password="password",
    )

    cmd = syncer._build_rsync_command()
    assert cmd[0] == "sshpass"
    assert cmd[1] == "-p"
    assert cmd[2] == "password"
    assert "rsync" in cmd


def test_rsync_missing_sshpass(mocker):
    """Test error raised when sshpass is missing."""
    mocker.patch("shutil.which", return_value=None)

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
        password="password",
    )

    with pytest.raises(SyncError, match="sshpass"):
        syncer.sync()


def test_rsync_download_command_generation():
    """Test download command generation."""
    import shlex

    syncer = RsyncSyncer(
        local_dir="/local/project",
        remote_dir="/remote/project",
        host="192.168.1.1",
        user="dev",
        key_filename="~/.ssh/id_rsa",
        exclude=[".git", "__pycache__"],
    )

    cmd_list = syncer._build_rsync_download_command("/remote/file.txt", "/local/file.txt")

    assert "rsync" in cmd_list[0]
    # Check for archive mode (silent mode uses -azq)
    assert "-azq" in cmd_list or any(x.startswith("-") and "a" in x and "q" in x for x in cmd_list)

    # Check source (remote path with shlex.quote)
    expected_src = f"dev@192.168.1.1:{shlex.quote('/remote/file.txt')}"
    assert expected_src in cmd_list

    # Check dest (local path)
    assert "/local/file.txt" in cmd_list

    # Check SSH args
    assert "-e" in cmd_list
    e_index = cmd_list.index("-e")
    ssh_cmd = cmd_list[e_index + 1]
    assert "ssh" in ssh_cmd
    assert "-i ~/.ssh/id_rsa" in ssh_cmd


def test_rsync_download_command_generation_with_progress():
    """Test download command generation in progress mode."""
    import shlex

    syncer = RsyncSyncer(
        local_dir="/local/project",
        remote_dir="/remote/project",
        host="192.168.1.1",
        user="dev",
        key_filename="~/.ssh/id_rsa",
        exclude=[".git", "__pycache__"],
    )

    cmd_list = syncer._build_rsync_download_command("/remote/file.txt", "/local/file.txt", show_progress=True)

    assert "rsync" in cmd_list[0]
    # Check for archive mode with verbose (progress mode uses -av --info=NAME)
    assert "-av" in cmd_list or any(x.startswith("-") and "a" in x and "v" in x for x in cmd_list)
    assert "--info=NAME" in cmd_list

    # Check that -q (quiet) is NOT in progress mode
    assert "-azq" not in cmd_list
    assert not any(x.startswith("-") and "q" in x for x in cmd_list)

    # Check source (remote path with shlex.quote)
    expected_src = f"dev@192.168.1.1:{shlex.quote('/remote/file.txt')}"
    assert expected_src in cmd_list


def test_rsync_version_check_supported(mocker):
    """Test rsync version check when version is supported (>= 3.1.0)."""
    mock_result = mocker.MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "rsync  version 3.2.5  protocol version 31\n"
    mocker.patch("subprocess.run", return_value=mock_result)

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
    )

    version = syncer._check_rsync_version()
    assert version == (3, 2, 5)
    assert syncer._is_rsync_version_supported() is True


def test_rsync_version_check_unsupported(mocker):
    """Test rsync version check when version is too old (< 3.1.0)."""
    mock_result = mocker.MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "rsync  version 2.6.9  protocol version 29\n"
    mocker.patch("subprocess.run", return_value=mock_result)

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
    )

    version = syncer._check_rsync_version()
    assert version == (2, 6, 9)
    assert syncer._is_rsync_version_supported() is False


def test_rsync_version_check_not_found(mocker):
    """Test rsync version check when rsync is not installed."""
    mocker.patch("subprocess.run", side_effect=FileNotFoundError())

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
    )

    with pytest.raises(SyncError, match="rsync not found"):
        syncer._check_rsync_version()

    assert syncer._is_rsync_version_supported() is False


def test_rsync_sync_with_old_version_shows_error(mocker):
    """Test that sync with progress mode fails on old rsync version."""
    # Mock version check to return old version
    mock_result = mocker.MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "rsync  version 2.6.9  protocol version 29\n"
    mocker.patch("subprocess.run", return_value=mock_result)

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
        key_filename="~/.ssh/id_rsa",
    )

    def dummy_callback(filename):
        pass

    with pytest.raises(SyncError, match="rsync version 2.6.9 is too old"):
        syncer.sync(show_progress=True, progress_callback=dummy_callback)


def test_rsync_download_with_sshpass(mocker):
    """Test sshpass command generation for download."""
    mocker.patch("shutil.which", return_value="/usr/bin/sshpass")

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
        password="password",
    )

    cmd = syncer._build_rsync_download_command("/remote/file.txt", "/local/file.txt")
    assert cmd[0] == "sshpass"
    assert cmd[1] == "-p"
    assert cmd[2] == "password"
    assert "rsync" in cmd


def test_rsync_download_missing_sshpass(mocker):
    """Test error raised when sshpass is missing for download."""
    mocker.patch("shutil.which", return_value=None)

    syncer = RsyncSyncer(
        local_dir="/local",
        remote_dir="/remote",
        host="host",
        user="user",
        password="password",
    )

    with pytest.raises(SyncError, match="sshpass"):
        syncer.download("/remote/file.txt", "/local/file.txt")
