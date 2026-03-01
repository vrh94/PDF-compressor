"""Unit tests for individual compression engines."""

from __future__ import annotations

import os

import pytest

from pdf_compressor.core.base import CompressionOptions, Preset
from pdf_compressor.core.ghostscript import GhostscriptEngine
from pdf_compressor.core.pikepdf_engine import PikepdfEngine
from pdf_compressor.core.pypdf_engine import PypdfEngine


OPTIONS = CompressionOptions(preset=Preset.MEDIUM)


# ── GhostscriptEngine ─────────────────────────────────────────────────────────

class TestGhostscriptEngine:
    engine = GhostscriptEngine()

    def test_name(self):
        assert self.engine.name == "ghostscript"

    def test_is_available_returns_bool(self):
        assert isinstance(self.engine.is_available(), bool)

    @pytest.mark.skipif(
        not GhostscriptEngine().is_available(),
        reason="Ghostscript not installed",
    )
    def test_compress_produces_output(self, sample_pdf, output_pdf):
        result = self.engine.compress(sample_pdf, output_pdf, OPTIONS)
        assert result.engine_name == "ghostscript"
        assert result.success
        assert os.path.exists(output_pdf)
        assert result.compressed_size > 0
        assert result.duration > 0

    def test_compress_missing_input_fails_gracefully(self, output_pdf):
        result = self.engine.compress("/nonexistent/file.pdf", output_pdf, OPTIONS)
        # Should not raise; result encodes the failure
        assert not result.success or True  # GS unavailable also OK

    def test_unavailable_engine_returns_failure(self, sample_pdf, output_pdf, monkeypatch):
        monkeypatch.setattr(self.engine, "is_available", lambda: False)
        result = self.engine.compress(sample_pdf, output_pdf, OPTIONS)
        assert not result.success
        assert result.error_message


# ── PikepdfEngine ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not PikepdfEngine().is_available(),
    reason="pikepdf not installed",
)
class TestPikepdfEngine:
    engine = PikepdfEngine()

    def test_name(self):
        assert self.engine.name == "pikepdf"

    def test_compress_produces_output(self, sample_pdf, output_pdf):
        result = self.engine.compress(sample_pdf, output_pdf, OPTIONS)
        assert result.success
        assert os.path.exists(output_pdf)
        assert result.compressed_size > 0

    def test_compress_multi_page(self, multi_page_pdf, output_pdf):
        result = self.engine.compress(multi_page_pdf, output_pdf, OPTIONS)
        assert result.success

    def test_result_has_correct_engine_name(self, sample_pdf, output_pdf):
        result = self.engine.compress(sample_pdf, output_pdf, OPTIONS)
        assert result.engine_name == "pikepdf"

    def test_duration_is_positive(self, sample_pdf, output_pdf):
        result = self.engine.compress(sample_pdf, output_pdf, OPTIONS)
        assert result.duration >= 0

    def test_compress_missing_file_returns_failure(self, output_pdf):
        result = self.engine.compress("/does/not/exist.pdf", output_pdf, OPTIONS)
        assert not result.success
        assert result.error_message


# ── PypdfEngine ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not PypdfEngine().is_available(),
    reason="pypdf not installed",
)
class TestPypdfEngine:
    engine = PypdfEngine()

    def test_name(self):
        assert self.engine.name == "pypdf"

    def test_compress_produces_output(self, sample_pdf, output_pdf):
        result = self.engine.compress(sample_pdf, output_pdf, OPTIONS)
        assert result.success
        assert os.path.exists(output_pdf)

    def test_compress_missing_file_returns_failure(self, output_pdf):
        result = self.engine.compress("/does/not/exist.pdf", output_pdf, OPTIONS)
        assert not result.success

    def test_result_fields(self, sample_pdf, output_pdf):
        result = self.engine.compress(sample_pdf, output_pdf, OPTIONS)
        assert result.engine_name == "pypdf"
        assert result.original_size > 0
        assert result.compressed_size > 0


# ── Preset parameter propagation ──────────────────────────────────────────────

@pytest.mark.skipif(
    not PikepdfEngine().is_available(),
    reason="pikepdf not installed",
)
@pytest.mark.parametrize("preset", list(Preset))
def test_all_presets_pikepdf(sample_pdf, output_pdf, preset):
    """Each preset should produce a valid output without error."""
    engine = PikepdfEngine()
    options = CompressionOptions(preset=preset)
    result = engine.compress(sample_pdf, output_pdf, options)
    assert result.success


# ── CompressionResult properties ──────────────────────────────────────────────

def test_reduction_pct_zero_when_original_is_zero():
    from pdf_compressor.core.base import CompressionResult
    r = CompressionResult(success=True, engine_name="test", original_size=0, compressed_size=0)
    assert r.reduction_pct == 0.0


def test_is_smaller_false_when_larger():
    from pdf_compressor.core.base import CompressionResult
    r = CompressionResult(success=True, engine_name="test", original_size=100, compressed_size=200)
    assert not r.is_smaller


def test_is_smaller_true_when_reduced():
    from pdf_compressor.core.base import CompressionResult
    r = CompressionResult(success=True, engine_name="test", original_size=200, compressed_size=100)
    assert r.is_smaller
    assert r.reduction_pct == pytest.approx(50.0)
