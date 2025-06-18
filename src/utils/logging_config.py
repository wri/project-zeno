import logging
import sys
from logging.handlers import RotatingFileHandler

# Define the formatter
formatter = logging.Formatter(
    "{asctime} | {levelname:<8s} | {message}", 
    style="{",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Define handlers
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.INFO)

file_handler = RotatingFileHandler("logs/zeno.log", maxBytes=10**6, backupCount=5)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)

def get_logger(name: str) -> logging.Logger:
    """
    Returns a logger with the specified name, configured to log to
    both console and a file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG) # Set the lowest level

    # Add handlers only if they haven't been added before
    if not logger.handlers:
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)
        # Prevent log messages from being propagated to the root logger
        logger.propagate = False

    return logger
