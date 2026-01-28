import os
import tempfile

import pytest

from mtr.logger import Logger, LogLevel, _NoOpLogger, get_logger, setup_logging


class TestLogger:
    """Test cases for Logger class."""

    def test_logger_initialization(self):
        """Test logger can be initialized with default values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            logger = Logger(log_file, LogLevel.INFO)

            assert logger.log_file == log_file
            assert logger.level == LogLevel.INFO

    def test_log_level_filtering(self):
        """Test that log levels are properly filtered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            logger = Logger(log_file, LogLevel.WARNING)

            logger.debug("debug message")
            logger.info("info message")
            logger.warning("warning message")
            logger.error("error message")

            # Read log file
            with open(log_file, "r") as f:
                content = f.read()

            # DEBUG and INFO should not be in the log
            assert "debug message" not in content
            assert "info message" not in content
            # WARNING and ERROR should be in the log
            assert "warning message" in content
            assert "error message" in content

    def test_log_format(self):
        """Test log message format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            logger = Logger(log_file, LogLevel.DEBUG)

            logger.info("test message", module="test_module")

            with open(log_file, "r") as f:
                content = f.read()

            # Check format: [YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message
            assert "[INFO]" in content
            assert "[test_module]" in content
            assert "test message" in content


class TestNoOpLogger:
    """Test cases for _NoOpLogger class."""

    def test_no_op_logger_methods(self):
        """Test that _NoOpLogger methods do nothing and don't raise."""
        logger = _NoOpLogger()

        # All methods should not raise any errors
        logger.debug("test")
        logger.info("test")
        logger.warning("test")
        logger.error("test")

    def test_no_op_logger_with_module(self):
        """Test that _NoOpLogger accepts module parameter."""
        logger = _NoOpLogger()

        # Should not raise with module parameter
        logger.info("test", module="test_module")
        logger.debug("test", module="another_module")


class TestSetupLogging:
    """Test cases for setup_logging function."""

    def test_setup_logging_creates_directory(self):
        """Test that setup_logging creates log directory if not exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "logs")
            log_file = os.path.join(log_dir, "test.log")

            assert not os.path.exists(log_dir)
            setup_logging(log_file, LogLevel.INFO)
            assert os.path.exists(log_dir)

    def test_setup_logging_returns_logger(self):
        """Test that setup_logging returns a logger instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            logger = setup_logging(log_file, LogLevel.DEBUG)

            assert isinstance(logger, Logger)
            assert logger.log_file == log_file
            assert logger.level == LogLevel.DEBUG

    def test_get_logger_returns_same_instance(self):
        """Test that get_logger returns the same logger instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")

            setup_logging(log_file, LogLevel.INFO)
            logger1 = get_logger()
            logger2 = get_logger()

            assert logger1 is logger2

    def test_get_logger_without_setup_returns_no_op(self):
        """Test that get_logger returns _NoOpLogger if setup not called."""
        # Reset the global logger
        import mtr.logger as logger_module

        logger_module._logger = None

        logger = get_logger()
        assert isinstance(logger, _NoOpLogger)

    def test_no_op_logger_does_not_write(self):
        """Test that _NoOpLogger does not write to any file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")

            # Reset to ensure we get NoOpLogger
            import mtr.logger as logger_module

            logger_module._logger = None

            logger = get_logger()
            logger.info("this should not be written")
            logger.error("this should also not be written")

            # File should not exist
            assert not os.path.exists(log_file)


class TestLogLevel:
    """Test cases for LogLevel enum."""

    def test_log_level_values(self):
        """Test LogLevel enum values."""
        assert LogLevel.DEBUG.value == 10
        assert LogLevel.INFO.value == 20
        assert LogLevel.WARNING.value == 30
        assert LogLevel.ERROR.value == 40

    def test_log_level_from_string(self):
        """Test converting string to LogLevel."""
        assert LogLevel.from_string("DEBUG") == LogLevel.DEBUG
        assert LogLevel.from_string("INFO") == LogLevel.INFO
        assert LogLevel.from_string("WARNING") == LogLevel.WARNING
        assert LogLevel.from_string("ERROR") == LogLevel.ERROR

        # Case insensitive
        assert LogLevel.from_string("debug") == LogLevel.DEBUG
        assert LogLevel.from_string("Info") == LogLevel.INFO

    def test_log_level_from_string_invalid(self):
        """Test that invalid string raises ValueError."""
        with pytest.raises(ValueError):
            LogLevel.from_string("INVALID")
