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

"""
CompressionManager — orchestrates all engines, validates outputs,
and selects the best (smallest valid) result.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from pdf_compressor.core.base import (
    CompressionEngine,
    CompressionOptions,
    CompressionResult,
)
from pdf_compressor.core.ghostscript import GhostscriptEngine
from pdf_compressor.core.pikepdf_engine import PikepdfEngine
from pdf_compressor.core.pypdf_engine import PypdfEngine
from pdf_compressor.utils.logging_config import get_logger
from pdf_compressor.utils.validation import validate_pdf_output

log = get_logger(__name__)

_ALL_ENGINES: list[CompressionEngine] = [
    GhostscriptEngine(),
    PikepdfEngine(),
    PypdfEngine(),
]


class CompressionManager:
    """
    Runs compression engines against a PDF and returns the smallest valid output.

    Engines are run either sequentially or in parallel (``options.threads > 1``).
    Each engine output is validated before being considered as a candidate.
    Temporary files are cleaned up unless ``options.keep_temp`` is True.
    """

    def __init__(self, engines: Optional[list[CompressionEngine]] = None) -> None:
        self._engines = engines if engines is not None else list(_ALL_ENGINES)

    # ── public API ────────────────────────────────────────────────────────────

    def compress(
        self,
        input_path: str,
        output_path: str,
        options: Optional[CompressionOptions] = None,
    ) -> tuple[CompressionResult, list[CompressionResult]]:
        """
        Compress *input_path* → *output_path*.

        Returns ``(best_result, all_results)`` where *best_result* is the
        smallest valid output (or the original if nothing improved it).
        """
        if options is None:
            options = CompressionOptions()

        engines = self._filter_engines(options)
        if not engines:
            result = CompressionResult(
                success=False,
                engine_name="manager",
                error_message="No compression engines are available.",
            )
            return result, []

        log.info(
            "Compressing %s with engines: %s",
            input_path,
            [e.name for e in engines],
        )

        tmpdir = tempfile.mkdtemp(prefix="pdfcomp_")
        try:
            all_results = self._run_all(input_path, tmpdir, engines, options)
            best = self._select_and_write(input_path, output_path, all_results)
            return best, all_results
        finally:
            if not options.keep_temp:
                shutil.rmtree(tmpdir, ignore_errors=True)

    # ── engine selection ──────────────────────────────────────────────────────

    def _filter_engines(self, options: CompressionOptions) -> list[CompressionEngine]:
        engines = self._engines

        # Filter by name if --engine flag was supplied
        if options.engines:
            names = {n.lower() for n in options.engines}
            engines = [e for e in engines if e.name in names]

        # Drop engines whose dependencies are missing
        return [e for e in engines if e.is_available()]

    # ── execution ─────────────────────────────────────────────────────────────

    def _run_all(
        self,
        input_path: str,
        tmpdir: str,
        engines: list[CompressionEngine],
        options: CompressionOptions,
    ) -> list[CompressionResult]:
        if options.threads > 1 and len(engines) > 1:
            return self._run_parallel(input_path, tmpdir, engines, options)
        return self._run_sequential(input_path, tmpdir, engines, options)

    def _run_sequential(
        self,
        input_path: str,
        tmpdir: str,
        engines: list[CompressionEngine],
        options: CompressionOptions,
    ) -> list[CompressionResult]:
        results = []
        for engine in engines:
            out = os.path.join(tmpdir, f"{engine.name}_out.pdf")
            log.info("Running engine: %s", engine.name)
            result = engine.compress(input_path, out, options)
            result = self._validate_result(result)
            log.info("  %s", result)
            results.append(result)
        return results

    def _run_parallel(
        self,
        input_path: str,
        tmpdir: str,
        engines: list[CompressionEngine],
        options: CompressionOptions,
    ) -> list[CompressionResult]:
        futures_map = {}
        with ThreadPoolExecutor(max_workers=options.threads) as pool:
            for engine in engines:
                out = os.path.join(tmpdir, f"{engine.name}_out.pdf")
                log.info("Submitting engine: %s", engine.name)
                fut = pool.submit(engine.compress, input_path, out, options)
                futures_map[fut] = engine.name

        results = []
        for fut in as_completed(futures_map):
            try:
                result = fut.result()
            except Exception as exc:
                name = futures_map[fut]
                result = CompressionResult(
                    success=False,
                    engine_name=name,
                    error_message=str(exc),
                )
            result = self._validate_result(result)
            log.info("  %s", result)
            results.append(result)
        return results

    # ── validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_result(result: CompressionResult) -> CompressionResult:
        """Verify the output file is a readable, non-empty PDF."""
        if not result.success or not result.output_path:
            return result
        ok, msg = validate_pdf_output(result.output_path)
        if not ok:
            result.success = False
            result.error_message = f"Validation failed: {msg}"
            log.warning("Engine %s produced invalid output: %s", result.engine_name, msg)
        return result

    # ── selection ─────────────────────────────────────────────────────────────

    @staticmethod
    def _select_and_write(
        input_path: str,
        output_path: str,
        all_results: list[CompressionResult],
    ) -> CompressionResult:
        try:
            original_size = os.path.getsize(input_path)
        except OSError:
            original_size = 0

        valid = sorted(
            [r for r in all_results if r.is_smaller],
            key=lambda r: r.compressed_size,
        )

        if valid:
            best = valid[0]
            shutil.copy2(best.output_path, output_path)
            log.info(
                "Best engine: %s (%.1f%% smaller)",
                best.engine_name,
                best.reduction_pct,
            )
            return CompressionResult(
                success=True,
                engine_name=best.engine_name,
                original_size=original_size,
                compressed_size=best.compressed_size,
                output_path=output_path,
                duration=best.duration,
            )

        # No engine improved the file — return the original (if it exists)
        try:
            shutil.copy2(input_path, output_path)
        except OSError as exc:
            log.error("Cannot copy original to output: %s", exc)
            return CompressionResult(
                success=False,
                engine_name="manager",
                original_size=original_size,
                error_message=f"No engine succeeded and original is unreadable: {exc}",
            )
        log.warning("No engine reduced the file size; original returned.")
        return CompressionResult(
            success=True,
            engine_name="original",
            original_size=original_size,
            compressed_size=original_size,
            output_path=output_path,
            error_message="No engine produced a smaller output; original returned.",
        )
