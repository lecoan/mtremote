import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import yaml


class ConfigError(Exception):
    """Base exception for configuration errors."""

    pass


@dataclass
class Config:
    """Holds the resolved configuration for a specific execution context."""

    target_server: str
    server_config: Dict[str, Any]
    global_defaults: Dict[str, Any]

    def get_respect_gitignore(self) -> bool:
        """Get respect_gitignore setting, default True.

        Priority: server config > global defaults > True (default)
        """
        # Check server config first
        if "respect_gitignore" in self.server_config:
            return self.server_config["respect_gitignore"]
        # Then check global defaults
        if "respect_gitignore" in self.global_defaults:
            return self.global_defaults["respect_gitignore"]
        # Default to True
        return True


class ConfigLoader:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._resolve_default_config_path()

    def _resolve_default_config_path(self) -> str:
        # Priority: ./.mtr/config.yaml -> ~/.config/mtr/config.yaml
        local_config = os.path.join(os.getcwd(), ".mtr", "config.yaml")
        if os.path.exists(local_config):
            return local_config

        user_config = os.path.expanduser("~/.config/mtr/config.yaml")
        if os.path.exists(user_config):
            return user_config

        # Fallback to local if neither exists (will fail later on read if needed, or we can handle it)
        return local_config

    def load(self, server_name: Optional[str] = None) -> Config:
        if not os.path.exists(self.config_path):
            raise ConfigError(f"Configuration file not found at: {self.config_path}")

        try:
            with open(self.config_path, "r") as f:
                raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"Failed to parse config file: {e}")

        servers = raw_config.get("servers", {})
        if not servers:
            raise ConfigError("No servers defined in configuration.")

        # Determine target server
        target_server = server_name
        if not target_server:
            # Check for 'default' field (supports both 'default' and 'defaults' key potential confusion,
            # let's stick to 'default' for server alias as per spec)
            target_server = raw_config.get("default")

        if not target_server:
            # Implicit default: first server
            # In Python 3.7+, dicts preserve insertion order
            target_server = next(iter(servers))

        if target_server not in servers:
            raise ConfigError(f"Server '{target_server}' not found in configuration.")

        server_config = servers[target_server]

        # Merge global defaults into server config if needed
        # (This is a simplified merge, real one might need deep merge)
        global_defaults = raw_config.get("defaults", {})

        # Apply defaults to server config if keys are missing
        # For now, let's just return them separately or we can merge them.
        # The prompt implies we might want to use defaults.
        # Let's simple merge: defaults < server_config

        merged_config = global_defaults.copy()
        merged_config.update(server_config)

        return Config(
            target_server=target_server,
            server_config=merged_config,
            global_defaults=global_defaults,
        )
