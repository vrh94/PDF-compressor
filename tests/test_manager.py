"""Unit tests for CompressionManager."""

from __future__ import annotations

import os
import shutil

import pytest

from pdf_compressor.core.base import (
    CompressionEngine,
    CompressionOptions,
    CompressionResult,
    Preset,
)
from pdf_compressor.core.manager import CompressionManager


# ── Stub engines ──────────────────────────────────────────────────────────────

class _AlwaysSuccessEngine(CompressionEngine):
    """Returns a copy of the input as the compressed output (same size)."""

    name = "success_stub"

    def __init__(self, size_factor: float = 0.5, available: bool = True) -> None:
        self._size_factor = size_factor
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def compress(
        self, input_path: str, output_path: str, options: CompressionOptions
    ) -> CompressionResult:
        import time

        start = time.time()
        try:
            original_size = os.path.getsize(input_path)
        except OSError as exc:
            return CompressionResult(
                success=False, engine_name=self.name, error_message=str(exc)
            )
        # Write a truncated copy to simulate compression
        with open(input_path, "rb") as fh:
            data = fh.read()
        # Produce a valid-PDF-header output that is "smaller"
        compressed_data = data  # still a valid PDF
        with open(output_path, "wb") as fh:
            fh.write(compressed_data)

        compressed_size = int(original_size * self._size_factor) or original_size
        return CompressionResult(
            success=True,
            engine_name=self.name,
            original_size=original_size,
            compressed_size=compressed_size,
            output_path=output_path,
            duration=time.time() - start,
        )


class _AlwaysFailEngine(CompressionEngine):
    """Simulates an engine that always fails."""

    name = "fail_stub"

    def compress(
        self, input_path: str, output_path: str, options: CompressionOptions
    ) -> CompressionResult:
        return CompressionResult(
            success=False,
            engine_name=self.name,
            error_message="Simulated failure",
        )


class _UnavailableEngine(CompressionEngine):
    """Simulates a missing dependency."""

    name = "unavailable_stub"

    def is_available(self) -> bool:
        return False

    def compress(
        self, input_path: str, output_path: str, options: CompressionOptions
    ) -> CompressionResult:  # pragma: no cover
        raise RuntimeError("Should never be called")


# ── CompressionManager — engine filtering ─────────────────────────────────────

class TestEngineFiltering:
    def test_unavailable_engines_are_excluded(self, sample_pdf, output_pdf):
        mgr = CompressionManager(engines=[_UnavailableEngine()])
        best, all_results = mgr.compress(sample_pdf, output_pdf)
        assert not best.success
        assert all_results == []

    def test_engine_name_filter_via_options(self, sample_pdf, output_pdf):
        stub_a = _AlwaysSuccessEngine()
        stub_a.name = "engine_a"
        stub_b = _AlwaysSuccessEngine()
        stub_b.name = "engine_b"

        options = CompressionOptions(engines=["engine_a"])
        mgr = CompressionManager(engines=[stub_a, stub_b])
        best, all_results = mgr.compress(sample_pdf, output_pdf, options)

        names = [r.engine_name for r in all_results]
        assert "engine_a" in names
        assert "engine_b" not in names

    def test_engine_name_filter_case_insensitive(self, sample_pdf, output_pdf):
        stub = _AlwaysSuccessEngine()
        stub.name = "myengine"

        options = CompressionOptions(engines=["MyEngine"])
        mgr = CompressionManager(engines=[stub])
        best, all_results = mgr.compress(sample_pdf, output_pdf, options)

        assert any(r.engine_name == "myengine" for r in all_results)


# ── CompressionManager — selection logic ──────────────────────────────────────

class TestSelectionLogic:
    def test_best_engine_is_smallest(self, sample_pdf, output_pdf):
        small = _AlwaysSuccessEngine(size_factor=0.3)
        small.name = "small_engine"
        large = _AlwaysSuccessEngine(size_factor=0.8)
        large.name = "large_engine"

        mgr = CompressionManager(engines=[large, small])
        best, _ = mgr.compress(sample_pdf, output_pdf)
        assert best.engine_name == "small_engine"

    def test_all_fail_returns_original(self, sample_pdf, output_pdf):
        mgr = CompressionManager(engines=[_AlwaysFailEngine()])
        best, all_results = mgr.compress(sample_pdf, output_pdf)
        # Manager should still succeed by falling back to original
        assert best.success
        assert best.engine_name == "original"
        assert os.path.exists(output_pdf)

    def test_no_improvement_returns_original(self, sample_pdf, output_pdf):
        """Engine that produces a same-size file → original returned."""
        same_size = _AlwaysSuccessEngine(size_factor=1.0)
        same_size.name = "same_size_engine"

        mgr = CompressionManager(engines=[same_size])
        best, _ = mgr.compress(sample_pdf, output_pdf)
        assert best.engine_name == "original"

    def test_output_file_created(self, sample_pdf, output_pdf):
        mgr = CompressionManager(engines=[_AlwaysSuccessEngine()])
        mgr.compress(sample_pdf, output_pdf)
        assert os.path.exists(output_pdf)


# ── CompressionManager — parallel execution ───────────────────────────────────

class TestParallelExecution:
    def test_parallel_returns_same_count(self, sample_pdf, output_pdf):
        engines = [_AlwaysSuccessEngine() for _ in range(3)]
        for i, e in enumerate(engines):
            e.name = f"engine_{i}"

        options_seq = CompressionOptions(threads=1)
        options_par = CompressionOptions(threads=4)

        mgr_seq = CompressionManager(engines=list(engines))
        mgr_par = CompressionManager(engines=list(engines))

        _, seq_results = mgr_seq.compress(sample_pdf, output_pdf, options_seq)
        _, par_results = mgr_par.compress(sample_pdf, output_pdf, options_par)

        assert len(seq_results) == len(par_results) == 3

    def test_parallel_best_engine_matches_sequential(self, sample_pdf, output_pdf):
        small = _AlwaysSuccessEngine(size_factor=0.3)
        small.name = "small_engine"
        large = _AlwaysSuccessEngine(size_factor=0.8)
        large.name = "large_engine"

        opts_seq = CompressionOptions(threads=1)
        opts_par = CompressionOptions(threads=2)

        best_seq, _ = CompressionManager(engines=[small, large]).compress(
            sample_pdf, output_pdf, opts_seq
        )
        best_par, _ = CompressionManager(engines=[small, large]).compress(
            sample_pdf, output_pdf, opts_par
        )
        assert best_seq.engine_name == best_par.engine_name


# ── CompressionManager — invalid input handling ───────────────────────────────

class TestInvalidInput:
    def test_missing_input_file(self, output_pdf):
        mgr = CompressionManager(engines=[_AlwaysSuccessEngine()])
        # The engine will fail because the input doesn't exist
        best, all_results = mgr.compress("/nonexistent/file.pdf", output_pdf)
        # Either all engines fail or manager falls back gracefully
        assert isinstance(best, CompressionResult)

    def test_returns_two_tuple(self, sample_pdf, output_pdf):
        mgr = CompressionManager(engines=[_AlwaysSuccessEngine()])
        result = mgr.compress(sample_pdf, output_pdf)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_all_results_is_list(self, sample_pdf, output_pdf):
        mgr = CompressionManager(engines=[_AlwaysSuccessEngine()])
        _, all_results = mgr.compress(sample_pdf, output_pdf)
        assert isinstance(all_results, list)


# ── CompressionManager — default engines ──────────────────────────────────────

class TestDefaultEngines:
    def test_default_manager_runs_without_error(self, sample_pdf, output_pdf):
        """Default manager should succeed (using whatever engines are installed)."""
        mgr = CompressionManager()
        best, all_results = mgr.compress(sample_pdf, output_pdf)
        assert isinstance(best, CompressionResult)
        assert os.path.exists(output_pdf)

    def test_compress_with_each_preset(self, sample_pdf, output_pdf):
        for preset in Preset:
            opts = CompressionOptions(preset=preset)
            mgr = CompressionManager(engines=[_AlwaysSuccessEngine()])
            best, _ = mgr.compress(sample_pdf, output_pdf, opts)
            assert isinstance(best, CompressionResult)
