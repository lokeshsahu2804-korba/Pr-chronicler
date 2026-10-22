"""Logging configuration for PR Chronicler.

Configures dual-destination logging:
1. Terminal / Console (StreamHandler) for real-time operational feedback.
2. File output (FileHandler) to pr_chronicler.log for tracking and audit logs.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from app.config import settings


def setup_logging(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """Configure unified logging for console and file output.

    Args:
        log_level: Optional logging level override (e.g., 'DEBUG', 'INFO').
        log_file: Optional log file path override (default: pr_chronicler.log).

    Returns:
        The configured application logger instance.
    """
    level_name = (log_level or settings.log_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    file_path = log_file or settings.log_file

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler (Terminal output)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # File Handler (pr_chronicler.log output)
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(file_path, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Application logger
    app_logger = logging.getLogger("pr_chronicler")
    app_logger.setLevel(level)

    return app_logger


# Pre-configured application logger
logger = logging.getLogger("pr_chronicler")
