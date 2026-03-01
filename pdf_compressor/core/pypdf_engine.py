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

"""pypdf-based compression engine."""

from __future__ import annotations

import os
import time

from pdf_compressor.core.base import (
    CompressionEngine,
    CompressionOptions,
    CompressionResult,
)
from pdf_compressor.utils.logging_config import get_logger

log = get_logger(__name__)


class PypdfEngine(CompressionEngine):
    """
    Compression via pypdf.

    Applies content-stream compression and identical-object deduplication.
    Fastest engine; most effective on text-heavy PDFs with inefficient streams.
    """

    name = "pypdf"

    def is_available(self) -> bool:
        try:
            import pypdf  # noqa: F401
            return True
        except ImportError:
            return False

    def compress(
        self,
        input_path: str,
        output_path: str,
        options: CompressionOptions,
    ) -> CompressionResult:
        start = time.perf_counter()
        try:
            original_size = os.path.getsize(input_path)
        except OSError as exc:
            return self._fail(0, f"Cannot read input file: {exc}", start)

        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            return self._fail(original_size, "pypdf is not installed.", start)

        try:
            reader = PdfReader(input_path)
            writer = PdfWriter()

            for page in reader.pages:
                page.compress_content_streams()
                writer.add_page(page)

            writer.compress_identical_objects(
                remove_identicals=True,
                remove_orphans=True,
            )

            with open(output_path, "wb") as fh:
                writer.write(fh)

        except Exception as exc:
            log.debug("pypdf error: %s", exc)
            return self._fail(original_size, str(exc), start)

        if not os.path.exists(output_path):
            return self._fail(original_size, "pypdf produced no output file.", start)

        return self._success(
            original_size, os.path.getsize(output_path), output_path, start
        )
