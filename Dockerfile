# ── Stage 1: build dependencies ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --upgrade pip

# Install Python deps into a prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Install the package itself
COPY pyproject.toml README.md ./
COPY pdf_compressor/ pdf_compressor/
RUN pip install --no-cache-dir --prefix=/install --no-deps .


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim

# System dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create a non-root user for security
RUN useradd --create-home --shell /bin/sh appuser
USER appuser
WORKDIR /home/appuser/app

# Copy only the application code (no build artifacts)
COPY --chown=appuser:appuser pdf_compressor/ pdf_compressor/
COPY --chown=appuser:appuser pyproject.toml ./

EXPOSE 5000

# Healthcheck — hits the /health endpoint every 30 s
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" \
    || exit 1

# 1 worker: compression is CPU/memory intensive; 30-min timeout for large files
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "1", \
     "--timeout", "1800", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "pdf_compressor.web.app:application"]
