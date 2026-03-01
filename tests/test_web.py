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
Tests for the Flask web layer.

Uses Flask's built-in test client — no running server required.
Rate-limiter tests reset internal state between tests via monkeypatch.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip the entire module if Flask is not installed (web is an optional extra).
flask = pytest.importorskip("flask")

from pdf_compressor.web.app import create_app
from pdf_compressor.web.routes import _RateLimiter, _upload_limiter


# ── test app factory ──────────────────────────────────────────────────────────

@pytest.fixture()
def app():
    app = create_app()
    app.config["TESTING"] = True
    # Disable the 2 GB limit in tests so we can send tiny buffers.
    app.config["MAX_CONTENT_LENGTH"] = None
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear the rate limiter bucket before each test to prevent bleed-over."""
    _upload_limiter._buckets.clear()
    yield
    _upload_limiter._buckets.clear()


# ── helpers ───────────────────────────────────────────────────────────────────

def _pdf_upload(client, data: bytes = b"%PDF-1.4\n%%EOF", filename: str = "test.pdf"):
    """POST a file to /compress and return the response."""
    return client.post(
        "/compress",
        data={"file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


# ── healthcheck ───────────────────────────────────────────────────────────────

class TestHealthcheck:
    def test_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_returns_ok_body(self, client):
        r = client.get("/health")
        assert r.get_json()["status"] == "ok"


# ── security: upload validation ───────────────────────────────────────────────

class TestUploadSecurity:
    def test_no_file_returns_400(self, client):
        r = client.post("/compress", data={}, content_type="multipart/form-data")
        assert r.status_code == 400

    def test_non_pdf_extension_returns_400(self, client):
        r = _pdf_upload(client, filename="malware.exe")
        assert r.status_code == 400
        assert "PDF" in r.get_json()["error"]

    def test_pdf_extension_but_wrong_mime_returns_400(self, client):
        # .pdf extension, but content is a PNG (wrong magic bytes)
        r = _pdf_upload(client, data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        assert r.status_code == 400
        assert "valid PDF" in r.get_json()["error"]

    def test_path_traversal_in_filename_is_sanitised(self, client):
        # werkzeug's secure_filename strips directory components; the file
        # must not be saved to an arbitrary path.  The request must either
        # succeed (sanitised name) or return 400 (rejected), never 500.
        r = _pdf_upload(client, filename="../../etc/passwd.pdf")
        assert r.status_code in (200, 400)

    def test_empty_filename_returns_400(self, client):
        r = client.post(
            "/compress",
            data={"file": (io.BytesIO(b"%PDF-1.4"), "")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400

    def test_valid_pdf_returns_job_id(self, client):
        r = _pdf_upload(client)
        assert r.status_code == 200
        body = r.get_json()
        assert "job_id" in body
        assert len(body["job_id"]) == 36   # UUID4 format


# ── rate limiting ─────────────────────────────────────────────────────────────

class TestRateLimiter:
    """Unit tests for _RateLimiter independent of Flask routing."""

    def test_allows_requests_under_limit(self):
        limiter = _RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert limiter.is_allowed("ip1") is True

    def test_blocks_after_limit_exceeded(self):
        limiter = _RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.is_allowed("ip1")
        assert limiter.is_allowed("ip1") is False

    def test_different_keys_are_independent(self):
        limiter = _RateLimiter(max_requests=1, window_seconds=60)
        limiter.is_allowed("ip1")
        # ip1 is now at limit; ip2 should still be allowed
        assert limiter.is_allowed("ip1") is False
        assert limiter.is_allowed("ip2") is True

    def test_retry_after_is_positive_when_limited(self):
        limiter = _RateLimiter(max_requests=1, window_seconds=60)
        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")   # trigger limit
        assert limiter.retry_after("ip1") > 0

    def test_retry_after_is_zero_when_not_limited(self):
        limiter = _RateLimiter(max_requests=10, window_seconds=60)
        assert limiter.retry_after("fresh_ip") == 0

    def test_evict_stale_removes_old_buckets(self):
        import time
        limiter = _RateLimiter(max_requests=10, window_seconds=1)
        limiter.is_allowed("stale_ip")
        time.sleep(1.1)    # let the window expire
        limiter.evict_stale()
        assert "stale_ip" not in limiter._buckets


class TestRateLimitingIntegration:
    """Verify the /compress endpoint returns 429 when the limit is exhausted."""

    def test_compress_returns_429_when_limit_exceeded(self, client):
        # Exhaust the per-IP limit (10 per minute), then verify 429.
        # We mock is_allowed to return False immediately so the test is fast.
        with patch.object(_upload_limiter, "is_allowed", return_value=False):
            r = _pdf_upload(client)
        assert r.status_code == 429
        body = r.get_json()
        assert "error" in body

    def test_429_includes_retry_after_header(self, client):
        with patch.object(_upload_limiter, "is_allowed", return_value=False):
            with patch.object(_upload_limiter, "retry_after", return_value=42):
                r = _pdf_upload(client)
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == "42"


# ── job status and download routes ────────────────────────────────────────────

class TestJobRoutes:
    def test_status_unknown_job_returns_404(self, client):
        r = client.get("/status/nonexistent-job-id")
        assert r.status_code == 404

    def test_download_unknown_job_returns_404(self, client):
        r = client.get("/download/nonexistent-job-id")
        assert r.status_code == 404

    def test_status_running_job(self, client):
        """A job that starts but hasn't finished should return 'running'."""
        from pdf_compressor.web.routes import job_store

        jid = "test-running-job"
        job_store.create(jid, {
            "status": "running", "step": 1,
            "result_data": None, "download_name": None, "error": None,
        })
        r = client.get(f"/status/{jid}")
        assert r.status_code == 200
        assert r.get_json()["status"] == "running"
        # Cleanup
        job_store.pop(jid)

    def test_status_done_job_includes_sizes(self, client):
        from pdf_compressor.web.routes import job_store

        jid = "test-done-job"
        job_store.create(jid, {
            "status": "done", "step": 5,
            "result_data": b"%PDF-1.4\n%%EOF",
            "download_name": "out_reduced.pdf",
            "error": None,
            "original_size": "10.0 KB",
            "compressed_size": "6.0 KB",
            "reduction": "40.0%",
        })
        r = client.get(f"/status/{jid}")
        assert r.status_code == 200
        body = r.get_json()
        assert body["status"] == "done"
        assert body["reduction"] == "40.0%"
        # Cleanup
        job_store.pop(jid)

    def test_download_done_job_returns_pdf(self, client):
        from pdf_compressor.web.routes import job_store

        jid = "test-download-job"
        pdf_bytes = b"%PDF-1.4\n%%EOF"
        job_store.create(jid, {
            "status": "done", "step": 5,
            "result_data": pdf_bytes,
            "download_name": "file_reduced.pdf",
            "error": None,
            "original_size": "1.0 KB",
            "compressed_size": "0.5 KB",
            "reduction": "50.0%",
        })
        r = client.get(f"/download/{jid}")
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"
        assert r.data == pdf_bytes

    def test_download_pops_job_from_store(self, client):
        """Downloading a job should remove it — second download must 404."""
        from pdf_compressor.web.routes import job_store

        jid = "test-pop-job"
        job_store.create(jid, {
            "status": "done", "step": 5,
            "result_data": b"%PDF-1.4",
            "download_name": "f.pdf",
            "error": None,
            "original_size": "1 KB",
            "compressed_size": "1 KB",
            "reduction": "0%",
        })
        client.get(f"/download/{jid}")            # first download
        r = client.get(f"/download/{jid}")        # second download
        assert r.status_code == 404
