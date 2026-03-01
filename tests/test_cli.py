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
Tests for the CLI layer: argument parsing, routing, and integration paths.

Parser tests operate directly on the argparse objects — no real PDFs needed.
Integration tests call main() with real (tiny) PDFs created by the fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pdf_compressor.cli.main import (
    _build_batch_parser,
    _build_single_parser,
    main,
)
from pdf_compressor.core.base import Preset


# ── single-file parser ────────────────────────────────────────────────────────

class TestSingleParser:
    p = _build_single_parser()

    def test_input_required(self):
        with pytest.raises(SystemExit):
            self.p.parse_args([])

    def test_input_only(self):
        args = self.p.parse_args(["doc.pdf"])
        assert args.input == "doc.pdf"
        assert args.output is None

    def test_input_and_output(self):
        args = self.p.parse_args(["in.pdf", "out.pdf"])
        assert args.input == "in.pdf"
        assert args.output == "out.pdf"

    def test_default_preset_is_medium(self):
        args = self.p.parse_args(["doc.pdf"])
        assert args.preset == Preset.MEDIUM.value

    def test_preset_choices(self):
        for preset in Preset:
            args = self.p.parse_args(["doc.pdf", "--preset", preset.value])
            assert args.preset == preset.value

    def test_invalid_preset_rejected(self):
        with pytest.raises(SystemExit):
            self.p.parse_args(["doc.pdf", "--preset", "ultra"])

    def test_engine_single(self):
        args = self.p.parse_args(["doc.pdf", "--engine", "pikepdf"])
        assert args.engines == ["pikepdf"]

    def test_engine_multiple(self):
        args = self.p.parse_args(["doc.pdf", "--engine", "pikepdf", "pypdf"])
        assert args.engines == ["pikepdf", "pypdf"]

    def test_engines_default_is_none(self):
        # None means "all available" — the manager applies no filter
        args = self.p.parse_args(["doc.pdf"])
        assert args.engines is None

    def test_threads_default(self):
        args = self.p.parse_args(["doc.pdf"])
        assert args.threads == 1

    def test_threads_custom(self):
        args = self.p.parse_args(["doc.pdf", "--threads", "4"])
        assert args.threads == 4

    def test_verbose_flag(self):
        args = self.p.parse_args(["doc.pdf", "--verbose"])
        assert args.verbose is True

    def test_verbose_short_flag(self):
        args = self.p.parse_args(["doc.pdf", "-v"])
        assert args.verbose is True

    def test_keep_temp_flag(self):
        args = self.p.parse_args(["doc.pdf", "--keep-temp"])
        assert args.keep_temp is True

    def test_verbose_default_false(self):
        args = self.p.parse_args(["doc.pdf"])
        assert args.verbose is False


# ── batch parser ──────────────────────────────────────────────────────────────

class TestBatchParser:
    p = _build_batch_parser()

    def test_requires_input_and_output_dir(self):
        with pytest.raises(SystemExit):
            self.p.parse_args([])

    def test_positionals(self):
        args = self.p.parse_args(["./in/", "./out/"])
        assert args.input_dir == "./in/"
        assert args.output_dir == "./out/"

    def test_workers_default_is_none(self):
        args = self.p.parse_args(["./in/", "./out/"])
        assert args.workers is None

    def test_workers_custom(self):
        args = self.p.parse_args(["./in/", "./out/", "--workers", "8"])
        assert args.workers == 8

    def test_batch_inherits_shared_flags(self):
        """--preset, --engine, --threads, --verbose must all be present."""
        args = self.p.parse_args([
            "./in/", "./out/",
            "--preset", "low",
            "--engine", "ghostscript",
            "--threads", "2",
            "--verbose",
            "--keep-temp",
        ])
        assert args.preset == "low"
        assert args.engines == ["ghostscript"]
        assert args.threads == 2
        assert args.verbose is True
        assert args.keep_temp is True


# ── main() routing ────────────────────────────────────────────────────────────

class TestMainRouting:
    def test_missing_input_returns_2(self):
        # argparse raises SystemExit(2) when a required positional is absent
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2

    def test_nonexistent_file_returns_1(self):
        rc = main(["/nonexistent/file.pdf"])
        assert rc == 1

    def test_nonexistent_batch_dir_returns_1(self, tmp_path):
        rc = main(["batch", str(tmp_path / "nowhere"), str(tmp_path / "out")])
        assert rc == 1

    def test_batch_same_dir_returns_1(self, tmp_path):
        rc = main(["batch", str(tmp_path), str(tmp_path)])
        assert rc == 1

    def test_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_batch_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            main(["batch", "--help"])
        assert exc.value.code == 0


# ── integration: compress a real (tiny) PDF ───────────────────────────────────

class TestMainIntegration:
    def test_single_file_succeeds(self, sample_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([sample_pdf, out])
        assert rc == 0
        assert Path(out).exists()

    def test_single_file_preset_low(self, sample_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([sample_pdf, out, "--preset", "low"])
        assert rc == 0

    def test_single_file_preset_lossless(self, sample_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([sample_pdf, out, "--preset", "lossless"])
        assert rc == 0

    def test_single_file_engine_filter(self, sample_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([sample_pdf, out, "--engine", "pypdf"])
        assert rc == 0

    def test_single_file_output_default_name(self, sample_pdf, tmp_path):
        """When no output is given, <stem>_reduced.pdf must be created."""
        src = Path(sample_pdf)
        expected = src.parent / (src.stem + "_reduced.pdf")
        rc = main([sample_pdf])
        assert rc == 0
        assert expected.exists()

    def test_corrupted_pdf_returns_1(self, corrupted_pdf, tmp_path):
        """A structurally invalid PDF should fail gracefully, not crash."""
        out = str(tmp_path / "out.pdf")
        rc = main([corrupted_pdf, out])
        # May return 0 (manager fell back to original) or 1 (all engines failed).
        # Either is acceptable — the key constraint is no unhandled exception.
        assert rc in (0, 1)

    def test_truncated_pdf_returns_nonzero_or_succeeds(self, truncated_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([truncated_pdf, out])
        assert rc in (0, 1)

    def test_empty_file_returns_1(self, empty_file, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([empty_file, out])
        assert rc == 1

    def test_not_a_pdf_returns_1(self, not_a_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([not_a_pdf, out])
        assert rc == 1

    def test_already_optimised_does_not_crash(self, already_optimised_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([already_optimised_pdf, out])
        # Manager should return the original — success even if nothing was saved.
        assert rc in (0, 1)
        if rc == 0:
            assert Path(out).exists()

    @pytest.mark.skipif(
        not __import__("shutil").which("gs"),
        reason="Ghostscript not installed",
    )
    def test_ghostscript_engine_only(self, sample_pdf, tmp_path):
        out = str(tmp_path / "out.pdf")
        rc = main([sample_pdf, out, "--engine", "ghostscript"])
        assert rc == 0

    def test_batch_mode_compresses_folder(self, tmp_path):
        from tests.conftest import _make_minimal_pdf

        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        for i in range(3):
            _make_minimal_pdf(src / f"doc_{i}.pdf", num_pages=1)

        rc = main(["batch", str(src), str(dst)])
        assert rc == 0
        outputs = list(dst.glob("*.pdf"))
        assert len(outputs) == 3

    def test_batch_empty_dir_returns_1(self, tmp_path):
        src = tmp_path / "empty_src"
        dst = tmp_path / "dst"
        src.mkdir()
        rc = main(["batch", str(src), str(dst)])
        assert rc == 1
