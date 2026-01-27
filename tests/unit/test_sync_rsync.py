import pytest
from unittest.mock import MagicMock, patch
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
    cmd_str = " ".join(cmd_list)

    assert "rsync" in cmd_list[0]
    # Check for archive mode
    assert "-avz" in cmd_list or any(x.startswith("-") and "a" in x for x in cmd_list)

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
