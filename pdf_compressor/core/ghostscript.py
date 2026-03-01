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

"""Ghostscript-based compression engine."""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from pdf_compressor.core.base import (
    CompressionEngine,
    CompressionOptions,
    CompressionResult,
)
from pdf_compressor.utils.logging_config import get_logger

log = get_logger(__name__)

_TIMEOUT = 1800  # 30 minutes — large files can take a while


class GhostscriptEngine(CompressionEngine):
    """
    Compression via Ghostscript (``gs``).

    Re-renders the PDF at a lower DPI using Bicubic downsampling.
    Typically the most effective strategy for image-heavy PDFs.
    """

    name = "ghostscript"

    def is_available(self) -> bool:
        return shutil.which("gs") is not None

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

        if not self.is_available():
            return self._fail(original_size, "Ghostscript (gs) not found on PATH.", start)

        dpi = options.resolved_dpi()
        gs_setting = options.resolved_gs_setting()

        cmd = [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={gs_setting}",
            # Force downsampling — without explicit flags gs may skip rescaling
            "-dDownsampleColorImages=true",
            "-dDownsampleGrayImages=true",
            "-dDownsampleMonoImages=true",
            "-dColorImageDownsampleType=/Bicubic",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dColorImageDownsampleThreshold=1.0",
            "-dGrayImageDownsampleThreshold=1.0",
            f"-dColorImageResolution={dpi}",
            f"-dGrayImageResolution={dpi}",
            f"-dMonoImageResolution={min(dpi * 2, 300)}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
            f"-sOutputFile={output_path}",
            input_path,
        ]

        log.debug("Ghostscript command: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return self._fail(original_size, "Ghostscript timed out after 30 minutes.", start)
        except FileNotFoundError:
            return self._fail(original_size, "Ghostscript binary not found.", start)

        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace").strip()
            return self._fail(original_size, f"gs exited {proc.returncode}: {stderr}", start)

        if not os.path.exists(output_path):
            return self._fail(original_size, "Ghostscript produced no output file.", start)

        return self._success(
            original_size, os.path.getsize(output_path), output_path, start
        )
