"""Command-line interface for pdf-compressor."""

from __future__ import annotations

import argparse
import sys

from pdf_compressor.core.base import CompressionOptions, Preset
from pdf_compressor.core.manager import CompressionManager
from pdf_compressor.utils.file_utils import file_size_kb, fmt_size, safe_output_path
from pdf_compressor.utils.logging_config import setup_logging
from pdf_compressor.utils.validation import validate_pdf_path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf-compressor",
        description=(
            "Reduce PDF file size using multiple compression engines.\n"
            "Runs all available engines and keeps the smallest valid result."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  pdf-compressor document.pdf
  pdf-compressor large.pdf small.pdf --preset low
  pdf-compressor report.pdf --engine ghostscript pikepdf --preset high
  pdf-compressor scan.pdf --threads 3 --verbose
""",
    )
    p.add_argument("input", help="Path to the input PDF file.")
    p.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Path for the compressed output PDF. Defaults to <input>_reduced.pdf.",
    )
    p.add_argument(
        "--preset",
        choices=[p.value for p in Preset],
        default=Preset.MEDIUM.value,
        help="Compression preset (default: medium).",
    )
    p.add_argument(
        "--engine",
        nargs="+",
        dest="engines",
        metavar="ENGINE",
        help="Engine(s) to use: ghostscript, pikepdf, pypdf. Default: all available.",
    )
    p.add_argument(
        "--threads",
        type=int,
        default=1,
        metavar="N",
        help="Run engines in parallel across N threads (default: 1 = sequential).",
    )
    p.add_argument(
        "--keep-temp",
        action="store_true",
        help="Retain temporary engine output files for inspection.",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    setup_logging(verbose=args.verbose)

    # ── validate input ────────────────────────────────────────────────────────
    ok, err = validate_pdf_path(args.input)
    if not ok:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    try:
        output_path = safe_output_path(args.input, args.output)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    original_kb = file_size_kb(args.input)
    print(f"Input:  {args.input}  ({fmt_size(original_kb)})")
    print(f"Preset: {args.preset}  |  Threads: {args.threads}")

    # ── compress ──────────────────────────────────────────────────────────────
    options = CompressionOptions(
        preset=Preset(args.preset),
        engines=args.engines,
        threads=args.threads,
        keep_temp=args.keep_temp,
        verbose=args.verbose,
    )

    manager = CompressionManager()

    print("Running engines…")
    best, all_results = manager.compress(args.input, output_path, options)

    # ── report ────────────────────────────────────────────────────────────────
    for r in all_results:
        status = (
            f"✓ {fmt_size(r.compressed_size / 1024)}"
            if r.success
            else f"✗ {r.error_message}"
        )
        print(f"  [{r.engine_name:>12}]  {status}  ({r.duration:.1f}s)")

    print()
    if not best.success:
        print(f"ERROR: {best.error_message}", file=sys.stderr)
        return 1

    compressed_kb = file_size_kb(output_path)
    reduction = (1 - compressed_kb / original_kb) * 100 if original_kb else 0

    if best.engine_name == "original":
        print("No engine reduced the file size. Original copied to output.")
    else:
        print(
            f"Output: {output_path}  ({fmt_size(compressed_kb)})  "
            f"— {reduction:.1f}% smaller  [winner: {best.engine_name}]"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
