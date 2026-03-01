FROM python:3.11-slim

# Install Ghostscript (best compression engine)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# 1 worker — compression is CPU/memory intensive; 30-min timeout for large files
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "1800", "app:app"]
