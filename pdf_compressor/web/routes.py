"""Flask route handlers for the PDF Compressor web interface."""

from __future__ import annotations

import io
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from pdf_compressor.core.base import CompressionOptions, Preset
from pdf_compressor.core.manager import CompressionManager
from pdf_compressor.utils.file_utils import file_size_kb, fmt_size
from pdf_compressor.utils.logging_config import get_logger
from pdf_compressor.utils.validation import validate_upload_mime

log = get_logger(__name__)
blueprint = Blueprint("pdf", __name__)


# ── thread-safe job store ─────────────────────────────────────────────────────

class JobStore:
    """Minimal in-memory store for background compression jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, data: dict) -> None:
        with self._lock:
            self._jobs[job_id] = data

    def update(self, job_id: str, **kwargs: object) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(kwargs)

    def get(self, job_id: str) -> dict:
        with self._lock:
            return dict(self._jobs.get(job_id, {}))

    def pop(self, job_id: str) -> dict | None:
        with self._lock:
            return self._jobs.pop(job_id, None)


job_store = JobStore()


# ── sliding-window rate limiter ───────────────────────────────────────────────

class _RateLimiter:
    """
    In-process sliding-window rate limiter — no external dependencies.

    Suitable for a single gunicorn worker (workers=1, as this app is
    configured).  If you scale to multiple workers or processes, replace this
    with flask-limiter backed by Redis so the window is shared across workers:

        pip install flask-limiter[redis]
        limiter = Limiter(app, storage_uri="redis://localhost:6379")
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """
        Return True and record the hit if under the limit.
        Return False without recording if the limit is exceeded.
        """
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            timestamps = [t for t in self._buckets.get(key, []) if t > cutoff]
            if len(timestamps) >= self._max:
                self._buckets[key] = timestamps
                return False
            timestamps.append(now)
            self._buckets[key] = timestamps
            return True

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest hit in the window expires."""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            timestamps = sorted(t for t in self._buckets.get(key, []) if t > cutoff)
        if not timestamps:
            return 0
        return max(0, int(timestamps[0] + self._window - now) + 1)

    def evict_stale(self) -> None:
        """Drop buckets with no recent activity (call periodically to cap RAM)."""
        cutoff = time.time() - self._window
        with self._lock:
            stale = [k for k, ts in self._buckets.items() if not any(t > cutoff for t in ts)]
            for k in stale:
                del self._buckets[k]


# 10 compression uploads per IP per minute.
# This is intentionally conservative — compression is CPU-heavy and we run
# a single gunicorn worker.  Raise the limit if you add a job queue.
_upload_limiter = _RateLimiter(max_requests=10, window_seconds=60)


# ── background worker ─────────────────────────────────────────────────────────

def _run_compression(job_id: str, input_path: str, tmpdir: str, filename: str) -> None:
    import shutil

    options = CompressionOptions(preset=Preset.MEDIUM, threads=1)
    output_path = os.path.join(tmpdir, "output.pdf")

    try:
        manager = CompressionManager()
        original_kb = file_size_kb(input_path)

        # step updates mirror the frontend step indicators (1-4)
        # We patch the manager to emit step signals — simplest approach:
        # just report steps after the fact (sequential, predictable order).

        job_store.update(job_id, step=1)
        best, _ = manager.compress(input_path, output_path, options)

        if not best.success:
            job_store.update(job_id, status="error", error=best.error_message)
            return

        compressed_kb = file_size_kb(output_path)
        with open(output_path, "rb") as fh:
            data = fh.read()

        stem = Path(filename).stem
        reduction = (1 - compressed_kb / original_kb) * 100 if original_kb > 0 else 0

        job_store.update(
            job_id,
            status="done",
            step=5,
            result_data=data,
            download_name=f"{stem}_reduced.pdf",
            original_size=fmt_size(original_kb),
            compressed_size=fmt_size(compressed_kb),
            reduction=f"{reduction:.1f}%",
        )
    except Exception as exc:
        log.exception("Compression job %s failed", job_id)
        job_store.update(job_id, status="error", error=str(exc))
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmpdir, ignore_errors=True)


# ── routes ────────────────────────────────────────────────────────────────────

@blueprint.route("/")
def index() -> str:
    return render_template("index.html")


@blueprint.route("/health")
def health():
    """Healthcheck endpoint for Docker and load balancers."""
    return jsonify({"status": "ok"})


@blueprint.route("/compress", methods=["POST"])
def compress():
    # ── rate limiting ─────────────────────────────────────────────────────────
    # Use the direct TCP connection address — not X-Forwarded-For, which is
    # trivially spoofed by a client.  If you run behind a trusted reverse proxy
    # (nginx, Caddy) that rewrites remote_addr, set TRUSTED_PROXIES instead.
    client_ip = request.remote_addr or "unknown"
    if not _upload_limiter.is_allowed(client_ip):
        retry = _upload_limiter.retry_after(client_ip)
        log.warning("Rate limit exceeded for %s", client_ip)
        return (
            jsonify({"error": "Too many uploads. Please wait before trying again."}),
            429,
            {"Retry-After": str(retry)},
        )

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    # ── security checks ───────────────────────────────────────────────────────
    safe_name = secure_filename(f.filename)
    if not safe_name.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    if not validate_upload_mime(f.stream):
        return jsonify({"error": "File does not appear to be a valid PDF"}), 400

    # ── save upload & start job ───────────────────────────────────────────────
    tmpdir = tempfile.mkdtemp(prefix="pdfweb_")
    input_path = os.path.join(tmpdir, "input.pdf")
    f.save(input_path)

    job_id = str(uuid.uuid4())
    job_store.create(
        job_id,
        {
            "status": "running",
            "step": 0,
            "result_data": None,
            "download_name": None,
            "error": None,
        },
    )

    thread = threading.Thread(
        target=_run_compression,
        args=(job_id, input_path, tmpdir, safe_name),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@blueprint.route("/status/<job_id>")
def status(job_id: str):
    job = job_store.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    resp: dict = {
        "status": job["status"],
        "step": job.get("step", 0),
        "error": job.get("error"),
    }
    if job["status"] == "done":
        resp.update(
            {
                "original_size": job["original_size"],
                "compressed_size": job["compressed_size"],
                "reduction": job["reduction"],
            }
        )
    return jsonify(resp)


@blueprint.route("/download/<job_id>")
def download(job_id: str):
    job = job_store.pop(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "Job not ready or already downloaded"}), 404

    data = job["result_data"]
    download_name = job["download_name"] or "compressed.pdf"
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf",
    )
