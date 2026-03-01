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
