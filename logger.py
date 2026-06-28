"""
Centralized logging module for the YouTube Deep Search project.

Provides a single get_logger() function that all other modules import.
Configures:
  - Console output (StreamHandler) for immediate dev visibility
  - Rotating file output at logs/app.log (5MB per file, 5 backups)
  - Default log level: DEBUG (override with LOG_LEVEL env var)
  - Format: [2026-06-28 17:55:00] [INFO] [module_name] message
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# --- Configuration ---
LOG_DIR = "logs"
LOG_FILENAME = "app.log"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5

# Default to DEBUG as requested; override with LOG_LEVEL env var
DEFAULT_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()

# Map string to logging level
LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
LOG_LEVEL = LEVEL_MAP.get(DEFAULT_LEVEL, logging.DEBUG)

# Standard format: [timestamp] [LEVEL] [module] message
LOG_FORMAT = "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# --- One-time setup ---
_logging_initialized = False


def _setup_logging():
    """Configure root logger with console + rotating file handlers (idempotent)."""
    global _logging_initialized
    if _logging_initialized:
        return

    # Ensure logs directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)

    # Rotating file handler
    log_path = os.path.join(LOG_DIR, LOG_FILENAME)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    # Remove any existing handlers to avoid duplicates on re-import
    root_logger.handlers.clear()

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    _logging_initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Returns a named logger configured with the project's centralized settings.

    Args:
        name: Typically __name__ or a short identifier like "api", "yt_dlp", etc.

    Returns:
        A configured logging.Logger instance.

    Usage:
        from logger import get_logger
        logger = get_logger(__name__)
        logger.info("Search completed: found %d videos", count)
    """
    _setup_logging()
    return logging.getLogger(name)