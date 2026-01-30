"""Update checker for mtr-cli."""

import json
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from packaging import version

from mtr import __version__

PYPI_API_URL = "https://pypi.org/pypi/mtr-cli/json"
CACHE_DIR = Path.home() / ".cache" / "mtr"
CACHE_FILE = CACHE_DIR / "update_cache.json"
CHECK_INTERVAL_HOURS = 24


class UpdateChecker:
    """Check for updates from PyPI."""

    def __init__(self, current_version: str = __version__):
        self.current_version = version.parse(current_version)
        self.cache_file = CACHE_FILE

    def _ensure_cache_dir(self) -> None:
        """Ensure cache directory exists."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_cache(self) -> dict:
        """Load cache from file."""
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_cache(self, data: dict) -> None:
        """Save cache to file."""
        self._ensure_cache_dir()
        try:
            with open(self.cache_file, "w") as f:
                json.dump(data, f)
        except IOError:
            pass  # Silently fail if we can't write cache

    def should_check(self) -> bool:
        """Check if we should perform an update check."""
        # Check if disabled via environment variable
        if os.environ.get("MTR_DISABLE_UPDATE_CHECK", "").lower() in ("1", "true", "yes"):
            return False

        cache = self._load_cache()
        last_check = cache.get("last_check_time")

        if not last_check:
            return True

        try:
            last_check_time = datetime.fromisoformat(last_check)
            next_check_time = last_check_time + timedelta(hours=CHECK_INTERVAL_HOURS)
            return datetime.now() >= next_check_time
        except ValueError:
            return True

    def get_latest_version(self) -> Optional[str]:
        """Fetch latest version from PyPI."""
        try:
            with urllib.request.urlopen(PYPI_API_URL, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data["info"]["version"]
        except Exception:
            return None

    def check(self) -> Optional[str]:
        """Perform update check and return update message if available.

        Returns:
            Update message string if a new version is available, None otherwise.
        """
        if not self.should_check():
            return None

        latest_version_str = self.get_latest_version()

        # Save check result regardless of success (to avoid hammering PyPI on failures)
        cache_data = {
            "last_check_time": datetime.now().isoformat(),
            "current_version": str(self.current_version),
        }

        if latest_version_str:
            cache_data["latest_version"] = latest_version_str
            self._save_cache(cache_data)

            latest = version.parse(latest_version_str)
            if latest > self.current_version:
                return self._format_update_message(latest_version_str)
        else:
            self._save_cache(cache_data)

        return None

    def _format_update_message(self, latest_version: str) -> str:
        """Format update message."""
        return (
            f"\n"
            f"⚠️  Update available: {self.current_version} → {latest_version}\n"
            f"   Run: uv tool upgrade mtr-cli\n"
            f"   Or:  pip install -U mtr-cli\n"
        )

    def get_cached_update_message(self) -> Optional[str]:
        """Get update message from cache without making network request.

        Returns:
            Update message string if a new version was previously detected, None otherwise.
        """
        cache = self._load_cache()
        latest_version_str = cache.get("latest_version")

        if latest_version_str:
            latest = version.parse(latest_version_str)
            if latest > self.current_version:
                return self._format_update_message(latest_version_str)

        return None
