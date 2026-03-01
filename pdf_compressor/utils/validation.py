# PDF Compressor — reduce PDF file size using multiple engines.
# Copyright (C) 2026  vrh94
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Input and output PDF validation."""

from __future__ import annotations

import os

_PDF_MAGIC = b"%PDF"


def validate_pdf_path(path: str) -> tuple[bool, str]:
    """
    Check that *path* exists, is a file, and has a PDF magic header.

    Returns ``(ok, error_message)``.
    """
    if not os.path.exists(path):
        return False, f"File not found: {path}"
    if not os.path.isfile(path):
        return False, f"Not a file: {path}"
    if os.path.getsize(path) == 0:
        return False, "File is empty."
    try:
        with open(path, "rb") as fh:
            header = fh.read(4)
        if header != _PDF_MAGIC:
            return False, "File does not appear to be a PDF (missing %PDF header)."
    except OSError as exc:
        return False, f"Cannot read file: {exc}"
    return True, ""


def validate_pdf_output(path: str) -> tuple[bool, str]:
    """
    Verify that a compressed output file is a readable, non-empty PDF.

    Attempts to open the file with pikepdf for structural validation.
    Falls back to magic-byte check if pikepdf is not installed.

    Returns ``(ok, error_message)``.
    """
    ok, msg = validate_pdf_path(path)
    if not ok:
        return False, msg

    try:
        import pikepdf

        with pikepdf.open(path) as pdf:
            if len(pdf.pages) == 0:
                return False, "Compressed PDF has no pages."
        return True, ""
    except ImportError:
        # pikepdf not available — magic-byte check already passed
        return True, ""
    except Exception as exc:
        return False, f"PDF is unreadable: {exc}"


def validate_upload_mime(stream: object) -> bool:
    """
    Check that an uploaded file stream begins with the PDF magic bytes.

    *stream* must support ``read(n)`` and ``seek(0)``.
    Returns True for valid PDFs.
    """
    try:
        header = stream.read(4)  # type: ignore[attr-defined]
        stream.seek(0)           # type: ignore[attr-defined]
        return header == _PDF_MAGIC
    except Exception:
        return False
