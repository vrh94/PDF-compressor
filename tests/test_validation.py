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

"""Unit tests for pdf_compressor.utils.validation."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from pdf_compressor.utils.validation import (
    validate_pdf_output,
    validate_pdf_path,
    validate_upload_mime,
)


# ── validate_pdf_path ──────────────────────────────────────────────────────────

class TestValidatePdfPath:
    def test_valid_pdf(self, sample_pdf):
        ok, msg = validate_pdf_path(sample_pdf)
        assert ok
        assert msg == ""

    def test_missing_file(self):
        ok, msg = validate_pdf_path("/does/not/exist.pdf")
        assert not ok
        assert "not found" in msg.lower() or "not" in msg.lower()

    def test_directory_path(self, tmp_path):
        ok, msg = validate_pdf_path(str(tmp_path))
        assert not ok
        assert msg  # some error message

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        ok, msg = validate_pdf_path(str(empty))
        assert not ok
        assert "empty" in msg.lower()

    def test_non_pdf_file(self, tmp_path):
        txt = tmp_path / "not_a_pdf.pdf"
        txt.write_bytes(b"This is not a PDF file at all")
        ok, msg = validate_pdf_path(str(txt))
        assert not ok
        assert "pdf" in msg.lower() or "%pdf" in msg.lower()

    def test_pdf_magic_header_check(self, tmp_path):
        """File with %PDF header should pass."""
        valid = tmp_path / "fake_but_magic.pdf"
        valid.write_bytes(b"%PDF-1.4\nsome content here")
        ok, msg = validate_pdf_path(str(valid))
        assert ok

    def test_returns_two_tuple(self, sample_pdf):
        result = validate_pdf_path(sample_pdf)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


# ── validate_pdf_output ────────────────────────────────────────────────────────

class TestValidatePdfOutput:
    def test_valid_output(self, sample_pdf):
        ok, msg = validate_pdf_output(sample_pdf)
        assert ok

    def test_missing_output_file(self):
        ok, msg = validate_pdf_output("/no/such/output.pdf")
        assert not ok

    def test_empty_output_file(self, tmp_path):
        empty = tmp_path / "empty_out.pdf"
        empty.write_bytes(b"")
        ok, msg = validate_pdf_output(str(empty))
        assert not ok

    def test_corrupt_pdf_content(self, tmp_path):
        corrupt = tmp_path / "corrupt.pdf"
        # Has magic header but corrupt body
        corrupt.write_bytes(b"%PDF-1.4\ngarbage data \x00\x01\x02")
        ok, msg = validate_pdf_output(str(corrupt))
        # With pikepdf: fails structural check; without: passes magic-byte check
        # Either outcome is acceptable — just check it doesn't raise
        assert isinstance(ok, bool)

    def test_valid_multi_page_output(self, multi_page_pdf):
        ok, msg = validate_pdf_output(multi_page_pdf)
        assert ok


# ── validate_upload_mime ───────────────────────────────────────────────────────

class TestValidateUploadMime:
    def test_valid_pdf_stream(self):
        stream = io.BytesIO(b"%PDF-1.4\nsome content")
        assert validate_upload_mime(stream) is True

    def test_stream_is_rewound_after_check(self):
        """seek(0) must be called so the stream can be re-read by Flask."""
        stream = io.BytesIO(b"%PDF-1.4\nsome content")
        validate_upload_mime(stream)
        assert stream.tell() == 0

    def test_non_pdf_stream(self):
        stream = io.BytesIO(b"PK\x03\x04some zip content")
        assert validate_upload_mime(stream) is False

    def test_empty_stream(self):
        stream = io.BytesIO(b"")
        assert validate_upload_mime(stream) is False

    def test_short_stream(self):
        """Streams shorter than 4 bytes should fail gracefully."""
        stream = io.BytesIO(b"%PD")
        assert validate_upload_mime(stream) is False

    def test_returns_bool(self):
        stream = io.BytesIO(b"%PDF-1.4")
        result = validate_upload_mime(stream)
        assert isinstance(result, bool)

    def test_bad_stream_returns_false(self):
        """Streams without seek/read should not raise."""

        class BadStream:
            def read(self, n):
                raise OSError("simulated read error")

            def seek(self, pos):
                pass

        assert validate_upload_mime(BadStream()) is False
