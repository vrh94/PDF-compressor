"""File-system helpers shared across CLI, web, and desktop layers."""

from __future__ import annotations

import os
from pathlib import Path


def file_size_bytes(path: str) -> int:
    """Return file size in bytes."""
    return os.path.getsize(path)


def file_size_kb(path: str) -> float:
    """Return file size in kilobytes."""
    return os.path.getsize(path) / 1024


def fmt_size(kb: float) -> str:
    """Human-readable size string (KB or MB)."""
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb:.1f} KB"


def fmt_size_bytes(n: int) -> str:
    """Human-readable size from bytes."""
    return fmt_size(n / 1024)


def safe_output_path(input_path: str, output_path: str | None) -> str:
    """
    Resolve the output path.

    If *output_path* is None, derive it by appending ``_reduced`` to the stem.
    Raises ``ValueError`` if input and resolved output are the same file.
    """
    if output_path is None:
        p = Path(input_path)
        output_path = str(p.with_stem(p.stem + "_reduced"))

    if os.path.abspath(input_path) == os.path.abspath(output_path):
        raise ValueError("Input and output paths must be different.")

    return output_path
