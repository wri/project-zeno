import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import structlog
from structlog.types import Processor

# Keys to strip from console output in compact mode
_VERBOSE_KEYS = ("query", "request_id", "session_id", "thread_id", "user_id")


def _drop_verbose_keys(
    logger: logging.Logger, method_name: str, event_dict: dict
) -> dict:
    """Strip repetitive context vars for compact console output."""
    for key in _VERBOSE_KEYS:
        event_dict.pop(key, None)
    # Shorten logger name: src.agent.tools.generate_insights → generate_insights
    if "logger" in event_dict:
        event_dict["logger"] = event_dict["logger"].rsplit(".", 1)[-1]
    return event_dict


def get_log_level() -> int:
    """Get log level from environment variable."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def get_log_format() -> str:
    """Get log format from environment variable."""
    return os.getenv("LOG_FORMAT", "text").lower()


def is_verbose() -> bool:
    """Check if verbose console logging is enabled."""
    return os.getenv("LOG_VERBOSE", "true").lower() == "true"


def should_log_to_file() -> bool:
    """Check if logging to file is enabled."""
    return os.getenv("LOG_TO_FILE", "true").lower() == "true"


def get_log_file_path() -> str:
    """Get log file path from environment variable."""
    return os.getenv("LOG_FILE_PATH", "logs/zeno.log")


def configure_structlog() -> None:
    """Configure structlog to pass event dicts to stdlib ProcessorFormatter."""

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        context_class=dict,
        cache_logger_on_first_use=True,
    )


def setup_standard_logging() -> None:
    """Set up standard library logging handlers with per-handler formatting."""
    root_logger = logging.getLogger()

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    log_level = get_log_level()
    log_format = get_log_format()

    # Console handler: compact by default, verbose with LOG_VERBOSE=true
    console_processors: list[Processor] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
    ]
    if not is_verbose():
        console_processors.append(_drop_verbose_keys)

    if log_format == "json":
        console_processors.append(structlog.processors.JSONRenderer())
    else:
        console_processors.append(
            structlog.dev.ConsoleRenderer(colors=True, pad_event=28)
        )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=console_processors,
    )
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(console_formatter)
    stream_handler.setLevel(log_level)
    root_logger.addHandler(stream_handler)

    # File handler: always full detail, no colors
    if should_log_to_file():
        file_processors: list[Processor] = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        ]
        if log_format == "json":
            file_processors.append(structlog.processors.JSONRenderer())
        else:
            file_processors.append(
                structlog.dev.ConsoleRenderer(colors=False, pad_event=28)
            )

        file_formatter = structlog.stdlib.ProcessorFormatter(
            processors=file_processors,
        )

        log_file_path = get_log_file_path()
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file_path, maxBytes=10**6, backupCount=5
        )
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


def bind_request_logging_context(**kwargs) -> None:
    """
    Bind request context for structured logging.
    """

    structlog.contextvars.bind_contextvars(**kwargs)
