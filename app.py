#!/usr/bin/env python3
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

import io
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from reduce_size import (
    compress_ghostscript,
    compress_pikepdf,
    compress_pypdf,
    file_size_kb,
    fmt_size,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB

# In-memory job store  {job_id: dict}
_jobs: dict = {}
_jobs_lock = threading.Lock()


def _set(job_id: str, **kwargs):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _get(job_id: str) -> dict:
    with _jobs_lock:
        return dict(_jobs.get(job_id, {}))


# ── background worker ──────────────────────────────────────────────────────────

def _run(job_id: str):
    job = _get(job_id)
    input_path  = job["input_path"]
    output_path = job["output_path"]
    tmpdir      = job["tmpdir"]
    filename    = job["filename"]

    candidates = []

    try:
        # Step 1 — Ghostscript
        _set(job_id, step=1)
        gs_out = output_path + ".gs.tmp"
        if compress_ghostscript(input_path, gs_out):
            candidates.append((file_size_kb(gs_out), gs_out))

        # Step 2 — pikepdf
        _set(job_id, step=2)
        pk_out = output_path + ".pk.tmp"
        if compress_pikepdf(input_path, pk_out):
            candidates.append((file_size_kb(pk_out), pk_out))

        # Step 3 — pypdf
        _set(job_id, step=3)
        py_out = output_path + ".py.tmp"
        if compress_pypdf(input_path, py_out):
            candidates.append((file_size_kb(py_out), py_out))

        if not candidates:
            _set(job_id, status="error", error="No compression engine available.")
            return

        # Step 4 — pick best
        _set(job_id, step=4)
        original_kb = job["original_kb"]
        best_kb, best_tmp = min(candidates, key=lambda x: x[0])

        for kb, path in candidates:
            if path != best_tmp and os.path.exists(path):
                os.remove(path)

        if best_kb >= original_kb:
            shutil.copy2(input_path, output_path)
            best_kb = original_kb
        else:
            shutil.move(best_tmp, output_path)

        with open(output_path, "rb") as fh:
            data = fh.read()

        stem = Path(filename).stem
        reduction = (1 - best_kb / original_kb) * 100 if original_kb > 0 else 0

        _set(job_id,
             status="done",
             step=5,
             compressed_kb=best_kb,
             result_data=data,
             download_name=f"{stem}_reduced.pdf",
             original_size=fmt_size(original_kb),
             compressed_size=fmt_size(best_kb),
             reduction=f"{reduction:.1f}%")

    except Exception as exc:
        _set(job_id, status="error", error=str(exc))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/compress", methods=["POST"])
def compress():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    tmpdir      = tempfile.mkdtemp()
    input_path  = os.path.join(tmpdir, "input.pdf")
    output_path = os.path.join(tmpdir, "output.pdf")
    f.save(input_path)

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status":      "running",
            "step":        0,           # 0=queued 1=GS 2=pikepdf 3=pypdf 4=selecting 5=done
            "original_kb": file_size_kb(input_path),
            "compressed_kb": None,
            "result_data": None,
            "download_name": None,
            "error":       None,
            "tmpdir":      tmpdir,
            "input_path":  input_path,
            "output_path": output_path,
            "filename":    f.filename,
        }

    threading.Thread(target=_run, args=(job_id,), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    job = _get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    resp = {
        "status": job["status"],
        "step":   job["step"],
        "error":  job.get("error"),
    }
    if job["status"] == "done":
        resp.update({
            "original_size":   job["original_size"],
            "compressed_size": job["compressed_size"],
            "reduction":       job["reduction"],
        })
    return jsonify(resp)


@app.route("/download/<job_id>")
def download(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job["status"] != "done":
            return jsonify({"error": "Not ready"}), 404
        data          = job["result_data"]
        download_name = job["download_name"]
        del _jobs[job_id]   # free memory after download

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
