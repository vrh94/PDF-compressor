"""Shared pytest fixtures."""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import pytest


# ── minimal PDF factory ───────────────────────────────────────────────────────

def _make_minimal_pdf(path: Path, num_pages: int = 1) -> None:
    """
    Write the smallest valid PDF that can be opened by pikepdf/pypdf.
    Uses a hand-crafted PDF with one blank page per requested page count.
    """
    try:
        import pikepdf

        pdf = pikepdf.new()
        for _ in range(num_pages):
            page = pikepdf.Dictionary(
                Type=pikepdf.Name("/Page"),
                MediaBox=[0, 0, 612, 792],
            )
            pdf.pages.append(pikepdf.Page(page))
        pdf.save(str(path))
    except ImportError:
        # Fallback: write a raw minimal PDF without pikepdf
        _write_raw_pdf(path, num_pages)


def _write_raw_pdf(path: Path, num_pages: int) -> None:
    """Write a raw minimal 1-page PDF (no external deps)."""
    body = b"%PDF-1.4\n"
    offsets = []

    def obj(num: int, content: bytes) -> None:
        offsets.append(len(body))
        body.__class__  # keep mypy happy — we reassemble below

    # Assemble imperatively
    parts: list[bytes] = [b"%PDF-1.4\n"]
    off: list[int] = []

    def add(content: bytes) -> None:
        off.append(sum(len(p) for p in parts))
        parts.append(content)

    add(b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n")
    kids = b" ".join(f"{3 + i} 0 R".encode() for i in range(num_pages))
    add(f"2 0 obj\n<</Type /Pages /Kids [{kids.decode()}] /Count {num_pages}>>\nendobj\n".encode())
    for i in range(num_pages):
        add(f"{3 + i} 0 obj\n<</Type /Page /MediaBox [0 0 612 792] /Parent 2 0 R>>\nendobj\n".encode())

    xref_pos = sum(len(p) for p in parts)
    n = 2 + num_pages + 1
    xref = f"xref\n0 {n}\n0000000000 65535 f \n"
    for o in off:
        xref += f"{o:010d} 00000 n \n"
    trailer = f"trailer\n<</Size {n} /Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF\n"
    parts.append(xref.encode())
    parts.append(trailer.encode())

    path.write_bytes(b"".join(parts))


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test output files."""
    return tmp_path


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> str:
    """Path to a minimal valid single-page PDF."""
    p = tmp_path / "sample.pdf"
    _make_minimal_pdf(p, num_pages=1)
    return str(p)


@pytest.fixture()
def multi_page_pdf(tmp_path: Path) -> str:
    """Path to a minimal 3-page PDF."""
    p = tmp_path / "multi.pdf"
    _make_minimal_pdf(p, num_pages=3)
    return str(p)


@pytest.fixture()
def output_pdf(tmp_path: Path) -> str:
    """Destination path for compressed output."""
    return str(tmp_path / "output.pdf")
