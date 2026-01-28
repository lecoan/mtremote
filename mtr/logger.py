import os
from datetime import datetime
from enum import Enum
from typing import Optional


class LogLevel(Enum):
    """Log level enumeration."""

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40

    @classmethod
    def from_string(cls, level_str: str) -> "LogLevel":
        """Convert string to LogLevel (case-insensitive)."""
        level_map = {
            "DEBUG": cls.DEBUG,
            "INFO": cls.INFO,
            "WARNING": cls.WARNING,
            "ERROR": cls.ERROR,
        }
        level_upper = level_str.upper()
        if level_upper not in level_map:
            raise ValueError(f"Invalid log level: {level_str}")
        return level_map[level_upper]


class _NoOpLogger:
    """No-op logger that silently discards all log messages.

    This is returned by get_logger() when logging is not initialized.
    It provides the same interface as Logger but does nothing.
    """

    def debug(self, message: str, module: str = "") -> None:
        """No-op debug log."""
        pass

    def info(self, message: str, module: str = "") -> None:
        """No-op info log."""
        pass

    def warning(self, message: str, module: str = "") -> None:
        """No-op warning log."""
        pass

    def error(self, message: str, module: str = "") -> None:
        """No-op error log."""
        pass


class Logger:
    """Simple file-based logger."""

    def __init__(self, log_file: str, level: LogLevel = LogLevel.INFO):
        """Initialize logger.

        Args:
            log_file: Path to log file
            level: Minimum log level to record
        """
        self.log_file = log_file
        self.level = level

    def _write(self, level: LogLevel, message: str, module: str = ""):
        """Write log message to file if level is sufficient."""
        if level.value < self.level.value:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        module_str = f"[{module}]" if module else ""
        log_line = f"[{timestamp}] [{level.name}] {module_str} {message}\n"

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_line)

    def debug(self, message: str, module: str = ""):
        """Log debug message."""
        self._write(LogLevel.DEBUG, message, module)

    def info(self, message: str, module: str = ""):
        """Log info message."""
        self._write(LogLevel.INFO, message, module)

    def warning(self, message: str, module: str = ""):
        """Log warning message."""
        self._write(LogLevel.WARNING, message, module)

    def error(self, message: str, module: str = ""):
        """Log error message."""
        self._write(LogLevel.ERROR, message, module)


# Global logger instance
_logger: Optional[Logger] = None
# No-op logger singleton
_no_op_logger = _NoOpLogger()


def setup_logging(log_file: str, level: LogLevel = LogLevel.INFO) -> Logger:
    """Setup logging with file output.

    Args:
        log_file: Path to log file
        level: Minimum log level

    Returns:
        Configured logger instance
    """
    global _logger

    # Create log directory if not exists
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    _logger = Logger(log_file, level)
    return _logger


def get_logger():
    """Get the global logger instance.

    Returns:
        Logger instance if logging is initialized, otherwise a no-op logger.
        The returned object always has debug(), info(), warning(), error() methods.
    """
    global _logger
    if _logger is None:
        return _no_op_logger
    return _logger
