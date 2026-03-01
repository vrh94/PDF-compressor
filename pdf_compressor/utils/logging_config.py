"""Logging configuration for the pdf_compressor package."""

from __future__ import annotations

import logging
import sys

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FMT = "%H:%M:%S"


def setup_logging(verbose: bool = False) -> None:
    """
    Configure the root *pdf_compressor* logger.

    Call this once at application startup (CLI, web, desktop).
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))

    root = logging.getLogger("pdf_compressor")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the *pdf_compressor* namespace."""
    return logging.getLogger(name)
