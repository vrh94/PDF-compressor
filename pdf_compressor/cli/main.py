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

"""Command-line interface for pdf-compressor."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pdf_compressor.core.base import CompressionOptions, Preset
from pdf_compressor.core.manager import CompressionManager
from pdf_compressor.utils.file_utils import file_size_kb, fmt_size, fmt_size_bytes, safe_output_path
from pdf_compressor.utils.logging_config import setup_logging
from pdf_compressor.utils.validation import validate_pdf_path

# tqdm is optional — fall back to a simple counter so the rest of the code is
# unconditional.  Install with: pip install tqdm
try:
    from tqdm import tqdm as _TqdmCls
    _TQDM = True
except ImportError:
    _TqdmCls = None  # type: ignore[assignment,misc]
    _TQDM = False


# ── shared argument helper ────────────────────────────────────────────────────

def _add_shared_args(parser: argparse.ArgumentParser) -> None:
    """
    Attach compression flags that are identical for both single-file and batch
    commands.  Called once per parser — single source of truth for defaults.
    """
    parser.add_argument(
        "--preset",
        choices=[preset.value for preset in Preset],
        default=Preset.MEDIUM.value,
        help="Compression quality preset (default: medium).",
    )
    parser.add_argument(
        "--engine",
        nargs="+",
        dest="engines",
        metavar="ENGINE",
        help="Engine(s) to use: ghostscript, pikepdf, pypdf. Default: all available.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Per-file engine parallelism — run engines in parallel across N threads "
            "(default: 1 = sequential).  In batch mode this applies inside each worker."
        ),
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Retain temporary engine output files for inspection.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )


# ── parser: single-file mode ──────────────────────────────────────────────────

def _build_single_parser() -> argparse.ArgumentParser:
    """
    Parser for the default single-file command.

    Uses the same interface as the original flat script so that all existing
    invocations continue to work unchanged.
    """
    p = argparse.ArgumentParser(
        prog="pdf-compressor",
        description=(
            "Reduce PDF file size using multiple compression engines.\n"
            "Runs all available engines and keeps the smallest valid result.\n\n"
            "To compress a whole folder at once use the 'batch' subcommand:\n"
            "  pdf-compressor batch INPUT_DIR OUTPUT_DIR [options]"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  pdf-compressor document.pdf
  pdf-compressor large.pdf small.pdf --preset low
  pdf-compressor report.pdf --engine ghostscript pikepdf --preset high
  pdf-compressor scan.pdf --threads 3 --verbose

batch mode:
  pdf-compressor batch ./inbox/ ./compressed/
  pdf-compressor batch ./inbox/ ./out/ --workers 4 --preset low
  pdf-compressor batch --help
""",
    )
    p.add_argument("input", help="Path to the input PDF file.")
    p.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Path for the compressed output PDF. Defaults to <input>_reduced.pdf.",
    )
    _add_shared_args(p)
    return p


# ── parser: batch mode ────────────────────────────────────────────────────────

def _build_batch_parser() -> argparse.ArgumentParser:
    """
    Parser for the 'batch' subcommand.

    Routing decision (argv[0] == 'batch') happens before argparse sees the
    arguments, so this parser never needs to deal with single-file positionals.
    There is therefore no ambiguity between INPUT_DIR and the main parser's
    INPUT argument.
    """
    p = argparse.ArgumentParser(
        prog="pdf-compressor batch",
        description=(
            "Compress every PDF in INPUT_DIR and write results to OUTPUT_DIR.\n\n"
            "Uses multiprocessing — one worker process per file in parallel.\n"
            "Workers are recycled every 10 files (Python 3.11+) to bound RSS growth\n"
            "from pikepdf/Pillow C-heap allocations that pymalloc does not release.\n\n"
            "The --threads flag controls engine parallelism *within* each worker.\n"
            "Use --workers to control how many files are compressed in parallel."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  pdf-compressor batch ./inbox/ ./compressed/
  pdf-compressor batch ./scans/ ./out/ --workers 4 --preset low
  pdf-compressor batch ./docs/ ./small/ --engine pikepdf --workers 2 --verbose
""",
    )
    p.add_argument(
        "input_dir",
        help="Directory containing PDF files to compress (top-level only).",
    )
    p.add_argument(
        "output_dir",
        help="Directory to write compressed PDFs into (created if absent).",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Number of parallel worker processes "
            "(default: auto = min(file_count, cpu_count=%d)).  "
            "Each worker independently compresses one file at a time."
        ) % (os.cpu_count() or 4),
    )
    _add_shared_args(p)
    return p


# ── single-file handler ───────────────────────────────────────────────────────

def _run_single(args: argparse.Namespace) -> int:
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

    options = CompressionOptions(
        preset=Preset(args.preset),
        engines=args.engines,
        threads=args.threads,
        keep_temp=args.keep_temp,
        verbose=args.verbose,
    )

    print("Running engines…")
    best, all_results = CompressionManager().compress(args.input, output_path, options)

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


# ── batch handler ─────────────────────────────────────────────────────────────

def _run_batch(args: argparse.Namespace) -> int:
    from pdf_compressor.cli.batch import BatchResult, BatchSummary, compress_folder  # noqa: PLC0415

    options = CompressionOptions(
        preset=Preset(args.preset),
        engines=args.engines,
        threads=args.threads,
        keep_temp=args.keep_temp,
        verbose=args.verbose,
    )

    # Pre-count PDFs so tqdm has a meaningful total before any work starts.
    input_dir = os.path.abspath(args.input_dir)
    pdfs = sorted(set(Path(input_dir).glob("*.pdf")) | set(Path(input_dir).glob("*.PDF")))
    pdf_count = len(pdfs)

    if pdf_count == 0:
        print(f"ERROR: No PDF files found in {args.input_dir}", file=sys.stderr)
        return 1

    print(
        f"Batch: {pdf_count} file(s)  |  "
        f"preset={args.preset}  "
        f"workers={args.workers or 'auto'}  "
        f"engine-threads={args.threads}"
    )

    # ── progress tracking ─────────────────────────────────────────────────────
    # The on_progress callback always runs in the main process after each
    # future resolves — safe to update tqdm or print from here.
    if _TQDM:
        pbar = _TqdmCls(
            total=pdf_count,
            unit="file",
            dynamic_ncols=True,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        )

        def _on_progress(result: BatchResult) -> None:
            name = Path(result.input_path).name
            r = result.result
            if r.success:
                if r.engine_name == "original":
                    line = f"  = {name:<40}  (no reduction)"
                else:
                    line = (
                        f"  \u2713 {name:<40}  "
                        f"\u2212{r.reduction_pct:.1f}%  "
                        f"[{r.engine_name}]  "
                        f"({result.wall_time:.1f}s)"
                    )
            elif r.engine_name == "preflight":
                line = f"  ~ {name:<40}  skipped: {r.error_message}"
            else:
                msg = r.error_message[:60] + ("\u2026" if len(r.error_message) > 60 else "")
                line = f"  \u2717 {name:<40}  FAILED: {msg}"

            # tqdm.write() repositions the cursor so the progress bar is not
            # overwritten by status text.
            _TqdmCls.write(line)
            pbar.update(1)

    else:
        # tqdm not installed — plain counter output.
        _state = {"n": 0}

        def _on_progress(result: BatchResult) -> None:  # type: ignore[misc]
            _state["n"] += 1
            name = Path(result.input_path).name
            r = result.result
            if r.success:
                tag = "=" if r.engine_name == "original" else "✓"
            elif r.engine_name == "preflight":
                tag = "~"
            else:
                tag = "✗"
            print(f"  [{_state['n']:>4}/{pdf_count}] {tag} {name}")

    # ── run ───────────────────────────────────────────────────────────────────
    summary: BatchSummary | None = None
    try:
        summary = compress_folder(
            args.input_dir,
            args.output_dir,
            options,
            workers=args.workers,
            on_progress=_on_progress,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if _TQDM:
            pbar.close()

    _print_batch_summary(summary)
    return 0 if summary.failed == 0 else 1


def _print_batch_summary(summary) -> None:  # type: ignore[no-untyped-def]
    divider = "\u2500" * 50
    print(f"\n{divider}")
    print("  Batch Summary")
    print(divider)
    print(f"  Total      {summary.total:>6} file(s)")
    print(f"  Succeeded  {summary.succeeded:>6}  ({summary.success_rate:.0f}%)")
    if summary.failed:
        print(f"  Failed     {summary.failed:>6}")
    if summary.skipped:
        print(f"  Skipped    {summary.skipped:>6}")
    print(f"  Saved      {fmt_size_bytes(summary.bytes_saved):>9}")
    print(f"  Elapsed    {summary.wall_time:>7.1f}s")
    print(divider)


# ── entry point ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """
    Route to single-file or batch mode before argparse sees the arguments.

    Using two separate parsers avoids the argparse ambiguity that arises when
    optional positionals (input/output) share a parser with subparsers: argparse
    would greedily consume 'batch' as the `input` positional rather than
    recognising it as a subcommand.

    Routing rule: if the first non-empty argument is exactly 'batch', delegate
    to the batch parser; otherwise use the single-file parser.
    """
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "batch":
        args = _build_batch_parser().parse_args(argv[1:])
        setup_logging(verbose=args.verbose)
        return _run_batch(args)

    args = _build_single_parser().parse_args(argv)
    setup_logging(verbose=args.verbose)
    return _run_single(args)


if __name__ == "__main__":
    sys.exit(main())
