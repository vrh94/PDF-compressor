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


# ── edge-case fixtures ────────────────────────────────────────────────────────

@pytest.fixture()
def corrupted_pdf(tmp_path: Path) -> str:
    """
    A file that starts with the %PDF magic bytes but has a structurally invalid
    body.  Every engine must return a failure result rather than raising.
    """
    p = tmp_path / "corrupted.pdf"
    # Valid magic header, then garbage — pikepdf/pypdf will reject it on parse.
    p.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Garbage /BrokenKey [\x00\xff\xfe] >>\n"
        b"This is not a valid PDF object stream.\n"
        b"%%EOF"
    )
    return str(p)


@pytest.fixture()
def truncated_pdf(tmp_path: Path) -> str:
    """
    A PDF whose content is cut off mid-stream — simulates a partial upload or
    a file that was written to disk but the write was interrupted.
    """
    p = tmp_path / "truncated.pdf"
    # Start like a real PDF but stop abruptly.
    p.write_bytes(b"%PDF-1.4\n1 0 obj\n<</Type /Catalog /Pages 2")
    return str(p)


@pytest.fixture()
def empty_file(tmp_path: Path) -> str:
    """A zero-byte file — should be rejected at validation before any engine runs."""
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    return str(p)


@pytest.fixture()
def not_a_pdf(tmp_path: Path) -> str:
    """A PNG file renamed to .pdf — MIME-type check should catch it."""
    p = tmp_path / "image.pdf"
    # Minimal PNG magic bytes
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return str(p)


@pytest.fixture()
def encrypted_pdf(tmp_path: Path) -> str:
    """
    A password-protected PDF (owner password = 'owner').

    Requires pikepdf.  Tests that use this fixture are automatically skipped
    if pikepdf is not installed — same pattern as the engine tests.
    """
    pytest.importorskip("pikepdf")
    import pikepdf

    p = tmp_path / "encrypted.pdf"
    pdf = pikepdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=[0, 0, 612, 792],
    )
    pdf.pages.append(pikepdf.Page(page))
    pdf.save(
        str(p),
        encryption=pikepdf.Encryption(owner="owner", user="", R=4),
    )
    return str(p)


@pytest.fixture()
def already_optimised_pdf(tmp_path: Path) -> str:
    """
    A minimal PDF that no engine can make smaller.  Used to verify that
    CompressionManager falls back to returning the original rather than a
    larger output.
    """
    p = tmp_path / "already_optimised.pdf"
    # The raw handcrafted PDF is already the smallest possible valid PDF —
    # it contains no compressible streams, no images, and no metadata.
    _write_raw_pdf(p, num_pages=1)
    return str(p)
