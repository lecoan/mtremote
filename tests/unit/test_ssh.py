"""Tests for SSH module."""

from unittest.mock import Mock, patch

import pytest

from mtr.ssh import SSHError, _build_command


def test_build_command():
    """Test command building with workdir and pre_cmd."""
    # Basic command
    assert _build_command("ls") == "ls"

    # With workdir
    assert _build_command("ls", workdir="/tmp") == "cd /tmp && ls"

    # With pre_cmd
    assert _build_command("python app.py", pre_cmd="source venv/bin/activate") == "source venv/bin/activate && python app.py"

    # With both
    assert (
        _build_command("python app.py", workdir="/app", pre_cmd="source venv/bin/activate")
        == "cd /app && source venv/bin/activate && python app.py"
    )
