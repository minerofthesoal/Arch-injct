"""
Logging configuration for the application.
"""

import logging
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

_configured = False


def setup_logging(verbose: bool = False):
    """Configure the root logger."""
    global _configured
    if _configured:
        return
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        stream=sys.stderr,
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    setup_logging()
    return logging.getLogger(name)
