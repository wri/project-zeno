import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

import structlog
from structlog.types import Processor


class ColorlessFormatter(logging.Formatter):
    """Custom formatter that strips ANSI color codes from log messages."""

    # ANSI escape sequence pattern
    ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return self.ANSI_ESCAPE.sub("", formatted)


def get_log_level() -> int:
    """Get log level from environment variable."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def get_log_format() -> str:
    """Get log format from environment variable."""
    return os.getenv("LOG_FORMAT", "text").lower()


def should_log_to_file() -> bool:
    """Check if logging to file is enabled."""
    return os.getenv("LOG_TO_FILE", "true").lower() == "true"


def get_log_file_path() -> str:
    """Get log file path from environment variable."""
    return os.getenv("LOG_FILE_PATH", "logs/zeno.log")


def configure_structlog() -> None:
    """Configure structlog with appropriate processors and output format."""

    # Common processors for all configurations
    shared_processors: list[Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    log_format = get_log_format()

    if log_format == "json":
        # JSON output configuration
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        # Text output configuration (default) - colors enabled for console
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                pad_event=28,
            )
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        context_class=dict,
        cache_logger_on_first_use=True,
    )


def setup_standard_logging() -> None:
    """Set up standard library logging handlers."""
    root_logger = logging.getLogger()

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    log_level = get_log_level()
    log_format = get_log_format()

    # Configure formatters based on output format
    if log_format == "json":
        # For JSON, we rely on structlog's JSONRenderer
        console_formatter = logging.Formatter("%(message)s")
        file_formatter = logging.Formatter("%(message)s")
    else:
        # For text, console gets colors, file gets colorless
        console_formatter = logging.Formatter("%(message)s")
        file_formatter = ColorlessFormatter("%(message)s")

    # Console handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(console_formatter)
    stream_handler.setLevel(log_level)
    root_logger.addHandler(stream_handler)

    # File handler (if enabled)
    if should_log_to_file():
        log_file_path = get_log_file_path()
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

        file_handler = RotatingFileHandler(log_file_path, maxBytes=10**6, backupCount=5)
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
        root_logger.addHandler(file_handler)

    root_logger.setLevel(logging.DEBUG)  # Let handlers control the level


# Configure structlog and standard logging on module import
setup_standard_logging()
configure_structlog()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Returns a structlog logger with the specified name.

    This function maintains backward compatibility with the existing
    logging interface while providing structured logging capabilities.

    Args:
        name: The logger name, typically __name__

    Returns:
        A configured structlog BoundLogger instance
    """
    return structlog.get_logger(name)


def bind_request_context(**kwargs) -> None:
    """
    Bind request context for structured logging.
    """

    structlog.contextvars.bind_contextvars(**kwargs)
