import pytest
import yaml

from mtr.config import ConfigError, ConfigLoader


@pytest.fixture
def sample_config_yaml(tmp_path):
    config_content = {
        "defaults": {"sync": "rsync", "exclude": [".git", "__pycache__"]},
        "servers": {
            "gpu-01": {
                "host": "192.168.1.10",
                "user": "dev",
                "key_filename": "~/.ssh/id_rsa",
                "remote_dir": "/data/codes/project_x",
            },
            "fallback-node": {
                "host": "10.0.0.5",
                "user": "dev",
                "password": "secret_password",
                "sync": "sftp",
            },
        },
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_content, f, sort_keys=False)
    return config_file


def test_load_default_server_implicit_first(sample_config_yaml):
    """Test that the first server is selected when no default is specified."""
    loader = ConfigLoader(config_path=str(sample_config_yaml))
    config = loader.load()

    assert config.target_server == "gpu-01"
    assert config.server_config["host"] == "192.168.1.10"


def test_load_default_server_explicit(tmp_path):
    """Test that the explicit default server is selected."""
    config_content = {
        "default": "node-2",
        "servers": {"node-1": {"host": "1.1.1.1"}, "node-2": {"host": "2.2.2.2"}},
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    loader = ConfigLoader(config_path=str(config_file))
    config = loader.load()

    assert config.target_server == "node-2"
    assert config.server_config["host"] == "2.2.2.2"


def test_server_override(sample_config_yaml):
    """Test that CLI argument overrides the default server."""
    loader = ConfigLoader(config_path=str(sample_config_yaml))
    config = loader.load(server_name="fallback-node")

    assert config.target_server == "fallback-node"
    assert config.server_config["host"] == "10.0.0.5"
    assert config.server_config["sync"] == "sftp"


def test_config_not_found():
    """Test that ConfigError is raised when config file is missing."""
    with pytest.raises(ConfigError):
        loader = ConfigLoader(config_path="/non/existent/path.yaml")
        loader.load()


def test_server_not_found(sample_config_yaml):
    """Test that ConfigError is raised when specified server doesn't exist."""
    loader = ConfigLoader(config_path=str(sample_config_yaml))
    with pytest.raises(ConfigError):
        loader.load(server_name="non-existent-server")


def test_respect_gitignore_default_true(tmp_path):
    """Test that respect_gitignore defaults to True when not specified."""
    config_content = {
        "defaults": {"sync": "rsync"},
        "servers": {"node-1": {"host": "1.1.1.1"}},
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    loader = ConfigLoader(config_path=str(config_file))
    config = loader.load()

    assert config.get_respect_gitignore() is True


def test_respect_gitignore_global_default(tmp_path):
    """Test that global defaults respect_gitignore is respected."""
    config_content = {
        "defaults": {"sync": "rsync", "respect_gitignore": False},
        "servers": {"node-1": {"host": "1.1.1.1"}},
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    loader = ConfigLoader(config_path=str(config_file))
    config = loader.load()

    assert config.get_respect_gitignore() is False


def test_respect_gitignore_server_override(tmp_path):
    """Test that server-level respect_gitignore overrides global default."""
    config_content = {
        "defaults": {"sync": "rsync", "respect_gitignore": True},
        "servers": {
            "node-1": {"host": "1.1.1.1", "respect_gitignore": False},
            "node-2": {"host": "2.2.2.2"},
        },
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    loader = ConfigLoader(config_path=str(config_file))

    # Server with override should return False
    config1 = loader.load(server_name="node-1")
    assert config1.get_respect_gitignore() is False

    # Server without override should use global default (True)
    config2 = loader.load(server_name="node-2")
    assert config2.get_respect_gitignore() is True
