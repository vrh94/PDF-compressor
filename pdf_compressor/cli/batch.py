"""
Batch compression — compress every PDF in a directory using worker processes.

Memory model
~~~~~~~~~~~~
Each PDF compression loads pikepdf (QPDF C++ bindings), Pillow image buffers,
and a Ghostscript subprocess into a worker process.  Python's allocator
(pymalloc) does not return freed C-extension pages to the OS promptly, so a
long-lived worker's RSS grows after each file even though Python objects have
been garbage-collected.

Fix: recycle workers every ``_TASKS_PER_CHILD`` files (Python 3.11+
``max_tasks_per_child``).  The OS reclaims the entire process heap on exit,
bounding peak RSS to roughly ``_TASKS_PER_CHILD × per-file peak``.

On Python 3.10 the pool works correctly; workers just grow slightly larger
over a very long batch.

Pickle contract
~~~~~~~~~~~~~~~
``_compress_one`` is a module-level function — required for
``ProcessPoolExecutor`` to serialise it across process boundaries via pickle.
``_Task`` is a plain dataclass whose fields are all picklable primitives.
``CompressionManager`` is instantiated *inside* the worker, never passed as an
argument: manager objects hold open ``tempfile`` directories and thread-pool
resources that must not be shared across process boundaries.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pdf_compressor.core.base import CompressionOptions, CompressionResult
from pdf_compressor.utils.file_utils import fmt_size_bytes
from pdf_compressor.utils.logging_config import get_logger

log = get_logger(__name__)

# Workers are recycled after this many tasks to release C-heap allocations.
# Raise this value on machines with abundant RAM; lower it on constrained hosts.
_TASKS_PER_CHILD = 10


# ── internal data types ───────────────────────────────────────────────────────

@dataclass
class _Task:
    """
    Everything a worker needs for one file — must stay fully picklable.

    All fields are primitives or plain dataclasses with primitive fields.
    Notably, ``CompressionOptions`` contains only str-enum, int, bool, and
    Optional[list[str]] — all pickle-safe.
    """

    input_path: str
    output_path: str
    options: CompressionOptions


# ── public data types ─────────────────────────────────────────────────────────

@dataclass
class BatchResult:
    """Outcome of a single file in a batch run."""

    input_path: str
    output_path: str
    result: CompressionResult
    wall_time: float = 0.0  # seconds from task dispatch to result received in main process


@dataclass
class BatchSummary:
    """Aggregated statistics for the entire batch."""

    total: int = 0          # files discovered in input_dir
    succeeded: int = 0      # files compressed (or returned as original) successfully
    failed: int = 0         # files where all engines failed
    skipped: int = 0        # files rejected at pre-flight validation
    bytes_saved: int = 0    # total bytes reduced across all successful files
    wall_time: float = 0.0  # total elapsed seconds
    results: list[BatchResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Percentage of attempted files that succeeded."""
        attempted = self.succeeded + self.failed
        return (self.succeeded / attempted * 100) if attempted else 0.0


# ── worker function ───────────────────────────────────────────────────────────
# Must be at module level — ProcessPoolExecutor pickles it by qualified name.

def _compress_one(task: _Task) -> BatchResult:
    """
    Worker entry point.  Runs inside a subprocess.

    Design rules:
    1. ``CompressionManager`` is created fresh per call — no shared state
       between workers or between successive calls in the same worker.
    2. Every exception is caught and encoded in the return value — a worker
       that raises would cause the corresponding ``Future`` to re-raise in
       the main process, but silent task loss is worse than a graceful failure.
    3. The return value contains only primitive data (ints, strings, floats).
       Returning large objects (bytes, file handles) would force pickle to
       serialise them back to the main process — avoid this.
    """
    t0 = time.perf_counter()
    try:
        # Import inside the function so the worker's import state is clean and
        # the module-level engine singletons in manager.py are fresh per process.
        from pdf_compressor.core.manager import CompressionManager  # noqa: PLC0415

        manager = CompressionManager()
        best, _ = manager.compress(task.input_path, task.output_path, task.options)
        return BatchResult(
            input_path=task.input_path,
            output_path=task.output_path,
            result=best,
            wall_time=time.perf_counter() - t0,
        )
    except Exception as exc:  # noqa: BLE001
        return BatchResult(
            input_path=task.input_path,
            output_path=task.output_path,
            result=CompressionResult(
                success=False,
                engine_name="batch_worker",
                error_message=f"Unhandled worker exception: {exc}",
            ),
            wall_time=time.perf_counter() - t0,
        )


# ── executor factory ──────────────────────────────────────────────────────────

def _make_executor(workers: int) -> ProcessPoolExecutor:
    """
    Build a ``ProcessPoolExecutor`` with optional worker recycling.

    ``max_tasks_per_child`` (added in Python 3.11) restarts a worker process
    after it has handled N tasks, releasing all C-heap allocations.  On
    Python 3.10, the argument is silently omitted and the pool works normally.
    """
    kwargs: dict = {"max_workers": workers}
    if sys.version_info >= (3, 11):
        kwargs["max_tasks_per_child"] = _TASKS_PER_CHILD
    return ProcessPoolExecutor(**kwargs)


# ── public API ────────────────────────────────────────────────────────────────

def compress_folder(
    input_dir: str,
    output_dir: str,
    options: CompressionOptions,
    workers: int | None = None,
    on_progress: Callable[[BatchResult], None] | None = None,
) -> BatchSummary:
    """
    Compress every PDF found directly inside *input_dir* and write results to
    *output_dir*.

    Parameters
    ----------
    input_dir:
        Source directory.  Only top-level ``*.pdf`` files are processed
        (case-insensitive on Windows; exact-case on Unix).
    output_dir:
        Destination directory.  Created if it does not exist.
        Must differ from *input_dir* (raises ``ValueError`` otherwise) to
        prevent overwriting originals.
    options:
        Shared ``CompressionOptions`` applied to every file.  The same preset,
        thread count, and engine filter are used for all files in the batch.
    workers:
        Number of parallel worker *processes*.  Defaults to
        ``min(file_count, cpu_count)``.  Each worker may itself spawn engine
        threads controlled by ``options.threads``, so total thread count is
        roughly ``workers × options.threads``.  Keep ``workers`` at or below
        ``cpu_count`` to avoid memory pressure — each worker holds one PDF in
        RAM at a time.
    on_progress:
        Optional callback invoked in the *main process* after each file
        completes (successfully or not), including skipped files.  Safe to
        call ``tqdm.update()`` or ``print()`` here.

    Returns
    -------
    BatchSummary
        Aggregate statistics.  Individual ``BatchResult`` objects are in
        ``summary.results`` in completion order (not input order).

    Raises
    ------
    ValueError
        If *input_dir* and *output_dir* resolve to the same path.
    """
    from pdf_compressor.utils.validation import validate_pdf_path  # noqa: PLC0415

    input_dir = os.path.abspath(input_dir)
    output_dir = os.path.abspath(output_dir)

    if input_dir == output_dir:
        raise ValueError(
            "input_dir and output_dir must be different paths to avoid overwriting originals."
        )

    os.makedirs(output_dir, exist_ok=True)

    # ── discover PDFs ─────────────────────────────────────────────────────────
    pdfs = sorted(Path(input_dir).glob("*.pdf"))
    # Also catch .PDF on case-sensitive file systems
    pdfs += [p for p in sorted(Path(input_dir).glob("*.PDF")) if p not in pdfs]

    summary = BatchSummary(total=len(pdfs))

    if not pdfs:
        log.warning("No PDF files found in %s", input_dir)
        return summary

    wall_start = time.perf_counter()

    # ── pre-flight validation ─────────────────────────────────────────────────
    # Catch obviously broken files before spawning workers — cheap and avoids
    # wasting a process slot on a zero-byte or plainly non-PDF file.
    tasks: list[_Task] = []
    for p in pdfs:
        ok, msg = validate_pdf_path(str(p))
        if not ok:
            log.warning("Skipping %s: %s", p.name, msg)
            summary.skipped += 1
            skipped_result = BatchResult(
                input_path=str(p),
                output_path="",
                result=CompressionResult(
                    success=False,
                    engine_name="preflight",
                    error_message=msg,
                ),
            )
            summary.results.append(skipped_result)
            if on_progress:
                on_progress(skipped_result)
            continue

        # Output: same filename, _reduced suffix, in output_dir.
        # Using a suffix (not just the stem) is consistent with single-file mode
        # and prevents accidental overwrites if input_dir == output_dir were
        # somehow not caught above.
        output_path = str(Path(output_dir) / (p.stem + "_reduced.pdf"))
        tasks.append(_Task(str(p), output_path, options))

    if not tasks:
        log.error("All %d PDF(s) failed pre-flight validation.", summary.skipped)
        summary.wall_time = time.perf_counter() - wall_start
        return summary

    # ── dispatch ──────────────────────────────────────────────────────────────
    cpu_count = os.cpu_count() or 4
    effective_workers = min(workers or cpu_count, len(tasks), cpu_count)
    log.info(
        "Batch: %d files → %d workers, preset=%s, engine-threads=%d",
        len(tasks),
        effective_workers,
        options.preset.value,
        options.threads,
    )

    with _make_executor(effective_workers) as pool:
        # Map future → input filename for error reporting.
        # Submitting all tasks up-front lets the executor fill its worker
        # queue immediately rather than waiting for one to finish first.
        future_to_name: dict[Future[BatchResult], str] = {
            pool.submit(_compress_one, task): Path(task.input_path).name
            for task in tasks
        }

        for fut in as_completed(future_to_name):
            try:
                batch_result = fut.result()
            except Exception as exc:
                # _compress_one is designed to never raise, but guard anyway.
                name = future_to_name[fut]
                log.exception("Unexpected future exception for %s", name)
                batch_result = BatchResult(
                    input_path=name,
                    output_path="",
                    result=CompressionResult(
                        success=False,
                        engine_name="batch_future",
                        error_message=str(exc),
                    ),
                )

            # ── tally ─────────────────────────────────────────────────────
            if batch_result.result.success:
                summary.succeeded += 1
                summary.bytes_saved += max(
                    0,
                    batch_result.result.original_size - batch_result.result.compressed_size,
                )
            else:
                summary.failed += 1

            summary.results.append(batch_result)

            if on_progress:
                on_progress(batch_result)

    summary.wall_time = time.perf_counter() - wall_start
    log.info(
        "Batch complete: %d/%d succeeded (%d failed, %d skipped), %s saved, %.1fs",
        summary.succeeded,
        len(tasks),
        summary.failed,
        summary.skipped,
        fmt_size_bytes(summary.bytes_saved),
        summary.wall_time,
    )
    return summary
