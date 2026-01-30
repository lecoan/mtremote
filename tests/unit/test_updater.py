"""Tests for mtr.updater module."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from mtr.updater import CHECK_INTERVAL_HOURS, PYPI_API_URL, UpdateChecker


@pytest.fixture
def mock_cache_dir(tmp_path):
    """Create a temporary cache directory for testing."""
    cache_dir = tmp_path / ".cache" / "mtr"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def updater(mock_cache_dir):
    """Create an UpdateChecker with mocked cache location."""
    checker = UpdateChecker(current_version="0.3.0")
    checker.cache_file = mock_cache_dir / "update_cache.json"
    return checker


class TestGetLatestVersion:
    """Tests for get_latest_version method."""

    def test_get_latest_version_success(self, updater):
        """Test successful fetch of latest version from PyPI."""
        mock_response_data = b'{"info": {"version": "0.4.0"}}'

        class MockResponse:
            def read(self):
                return mock_response_data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse()) as mock_urlopen:
            result = updater.get_latest_version()

            assert result == "0.4.0"
            mock_urlopen.assert_called_once_with(PYPI_API_URL, timeout=5)

    def test_get_latest_version_failure(self, updater):
        """Test graceful handling of network failure."""
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            result = updater.get_latest_version()

            assert result is None

    def test_get_latest_version_invalid_json(self, updater):
        """Test handling of invalid JSON response."""

        class MockResponse:
            def read(self):
                return b"invalid json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse()):
            result = updater.get_latest_version()

            assert result is None


class TestShouldCheck:
    """Tests for should_check method."""

    def test_should_check_first_time(self, updater):
        """Test that check is performed on first run (no cache)."""
        assert updater.should_check() is True

    def test_should_check_after_interval(self, updater):
        """Test that check is performed after interval has passed."""
        # Create cache with old check time
        old_time = datetime.now() - timedelta(hours=CHECK_INTERVAL_HOURS + 1)
        cache_data = {"last_check_time": old_time.isoformat()}

        updater._save_cache(cache_data)

        assert updater.should_check() is True

    def test_should_not_check_within_interval(self, updater):
        """Test that check is not performed within interval."""
        # Create cache with recent check time
        recent_time = datetime.now() - timedelta(hours=CHECK_INTERVAL_HOURS - 1)
        cache_data = {"last_check_time": recent_time.isoformat()}

        updater._save_cache(cache_data)

        assert updater.should_check() is False

    def test_should_check_disabled_via_env(self, updater):
        """Test that check can be disabled via environment variable."""
        with patch.dict(os.environ, {"MTR_DISABLE_UPDATE_CHECK": "1"}):
            assert updater.should_check() is False

    def test_should_check_disabled_via_env_true(self, updater):
        """Test that check can be disabled via environment variable with 'true'."""
        with patch.dict(os.environ, {"MTR_DISABLE_UPDATE_CHECK": "true"}):
            assert updater.should_check() is False

    def test_should_check_disabled_via_env_yes(self, updater):
        """Test that check can be disabled via environment variable with 'yes'."""
        with patch.dict(os.environ, {"MTR_DISABLE_UPDATE_CHECK": "yes"}):
            assert updater.should_check() is False

    def test_should_check_invalid_cache_time(self, updater):
        """Test that check is performed if cache time is invalid."""
        cache_data = {"last_check_time": "invalid-time-format"}
        updater._save_cache(cache_data)

        assert updater.should_check() is True


class TestCheck:
    """Tests for check method."""

    def test_check_no_update_available(self, updater):
        """Test that no message is returned when no update is available."""
        with patch.object(updater, "get_latest_version", return_value="0.3.0"):
            result = updater.check()

            assert result is None

    def test_check_update_available(self, updater):
        """Test that update message is returned when update is available."""
        with patch.object(updater, "get_latest_version", return_value="0.4.0"):
            result = updater.check()

            assert result is not None
            assert "0.3.0" in result
            assert "0.4.0" in result
            assert "uv tool upgrade mtr-cli" in result
            assert "pip install -U mtr-cli" in result

    def test_check_network_failure(self, updater):
        """Test graceful handling of network failure during check."""
        with patch.object(updater, "get_latest_version", return_value=None):
            result = updater.check()

            assert result is None

    def test_check_saves_cache_on_success(self, updater):
        """Test that cache is saved after successful check."""
        with patch.object(updater, "get_latest_version", return_value="0.4.0"):
            updater.check()

            cache = updater._load_cache()
            assert "last_check_time" in cache
            assert cache["latest_version"] == "0.4.0"
            assert cache["current_version"] == "0.3.0"

    def test_check_saves_cache_on_failure(self, updater):
        """Test that cache is saved even on failure to avoid hammering PyPI."""
        with patch.object(updater, "get_latest_version", return_value=None):
            updater.check()

            cache = updater._load_cache()
            assert "last_check_time" in cache
            assert "latest_version" not in cache

    def test_check_skips_if_disabled(self, updater):
        """Test that check is skipped if disabled via environment variable."""
        with patch.dict(os.environ, {"MTR_DISABLE_UPDATE_CHECK": "1"}):
            with patch.object(updater, "get_latest_version") as mock_get:
                updater.check()
                mock_get.assert_not_called()


class TestGetCachedUpdateMessage:
    """Tests for get_cached_update_message method."""

    def test_get_cached_message_no_cache(self, updater):
        """Test that None is returned when no cache exists."""
        result = updater.get_cached_update_message()
        assert result is None

    def test_get_cached_message_update_available(self, updater):
        """Test that message is returned from cache when update is available."""
        cache_data = {
            "last_check_time": datetime.now().isoformat(),
            "latest_version": "0.4.0",
            "current_version": "0.3.0",
        }
        updater._save_cache(cache_data)

        result = updater.get_cached_update_message()

        assert result is not None
        assert "0.4.0" in result

    def test_get_cached_message_no_update(self, updater):
        """Test that None is returned when cached version is not newer."""
        cache_data = {
            "last_check_time": datetime.now().isoformat(),
            "latest_version": "0.3.0",
            "current_version": "0.3.0",
        }
        updater._save_cache(cache_data)

        result = updater.get_cached_update_message()

        assert result is None

    def test_get_cached_message_older_version(self, updater):
        """Test that None is returned when cached version is older."""
        cache_data = {
            "last_check_time": datetime.now().isoformat(),
            "latest_version": "0.2.0",
            "current_version": "0.3.0",
        }
        updater._save_cache(cache_data)

        result = updater.get_cached_update_message()

        assert result is None


class TestFormatUpdateMessage:
    """Tests for _format_update_message method."""

    def test_format_update_message(self, updater):
        """Test the format of update message."""
        message = updater._format_update_message("0.4.0")

        assert "0.3.0" in message  # current version
        assert "0.4.0" in message  # latest version
        assert "uv tool upgrade mtr-cli" in message
        assert "pip install -U mtr-cli" in message
        assert "⚠️" in message  # warning emoji


class TestCacheOperations:
    """Tests for cache file operations."""

    def test_ensure_cache_dir_creates_directory(self, updater, tmp_path):
        """Test that cache directory is created if it doesn't exist."""
        # Use a new path that doesn't exist
        new_cache_file = tmp_path / "new_cache" / "mtr" / "update_cache.json"
        updater.cache_file = new_cache_file

        updater._ensure_cache_dir()

        assert new_cache_file.parent.exists()

    def test_load_cache_nonexistent_file(self, updater):
        """Test loading cache when file doesn't exist."""
        updater.cache_file = Path("/nonexistent/path/cache.json")
        result = updater._load_cache()
        assert result == {}

    def test_load_cache_invalid_json(self, updater):
        """Test loading cache with invalid JSON."""
        updater._ensure_cache_dir()
        with open(updater.cache_file, "w") as f:
            f.write("invalid json")

        result = updater._load_cache()
        assert result == {}

    def test_save_cache_io_error(self, updater):
        """Test graceful handling of IO error when saving cache."""
        # Make cache file a directory to cause IO error
        updater._ensure_cache_dir()
        updater.cache_file.mkdir(parents=True, exist_ok=True)
        updater.cache_file = updater.cache_file / "subdir" / "file.json"

        # Should not raise exception
        updater._save_cache({"test": "data"})
