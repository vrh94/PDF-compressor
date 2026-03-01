# PDF Compressor

A production-ready toolkit for reducing PDF file size using multiple compression engines. Runs all available engines in parallel and automatically selects the smallest valid result.

## Features

- **Three compression engines** — Ghostscript, pikepdf, and pypdf run simultaneously; the best result wins
- **Four quality presets** — `low` / `medium` / `high` / `lossless` with sensible defaults
- **CLI tool** — compress PDFs from the terminal with fine-grained control
- **Web app** — drag-and-drop upload with live progress bar, runs in Docker
- **Desktop app** — standalone PyQt6 GUI for Windows, macOS, and Linux (no Python required)
- **Parallel execution** — run engines concurrently with `--threads N`
- **Output validation** — every compressed file is verified before being accepted

---

## Quick Start

### Install

```bash
pip install pikepdf pypdf Pillow        # Python engines (always available)
# Optional: install Ghostscript for best compression
brew install ghostscript                 # macOS
sudo apt-get install ghostscript        # Debian / Ubuntu
```

### CLI

```bash
# Compress with default settings (medium preset)
pdf-compressor document.pdf

# Specify output path and preset
pdf-compressor large.pdf small.pdf --preset low

# Use specific engines only
pdf-compressor report.pdf --engine ghostscript pikepdf

# Run engines in parallel across 3 threads
pdf-compressor scan.pdf --threads 3 --verbose
```

### As a Python library

```python
from pdf_compressor import CompressionManager, CompressionOptions, Preset

manager = CompressionManager()
options = CompressionOptions(preset=Preset.MEDIUM, threads=2)
best, all_results = manager.compress("input.pdf", "output.pdf", options)

print(f"Winner: {best.engine_name} — {best.reduction_pct:.1f}% smaller")
for r in all_results:
    print(f"  {r.engine_name}: {'✓' if r.success else '✗'} {r.reduction_pct:.1f}%")
```

---

## Compression Presets

| Preset     | DPI | JPEG Quality | Ghostscript setting | Use case                  |
|------------|-----|--------------|---------------------|---------------------------|
| `low`      | 72  | 50           | `/screen`           | Email / web sharing       |
| `medium`   | 150 | 72           | `/ebook`            | General use (default)     |
| `high`     | 200 | 85           | `/printer`          | Print-ready documents     |
| `lossless` | 300 | 95           | `/prepress`         | Archival, minimal change  |

---

## CLI Reference

```
pdf-compressor [input] [output] [options]

Positional arguments:
  input               Path to the input PDF file
  output              Path for the compressed output (default: <input>_reduced.pdf)

Options:
  --preset {low,medium,high,lossless}
                      Compression preset (default: medium)
  --engine ENGINE [ENGINE ...]
                      Engine(s) to use: ghostscript, pikepdf, pypdf
  --threads N         Run engines in parallel across N threads (default: 1)
  --keep-temp         Retain intermediate engine output files
  --verbose, -v       Enable DEBUG-level logging
```

### Example output

```
Input:  document.pdf  (487.3 MB)
Preset: medium  |  Threads: 1
Running engines…
  [ ghostscript]  ✓ 198.4 MB  (42.3s)
  [      pikepdf]  ✓ 312.1 MB  (18.7s)
  [       pypdf]  ✓ 481.0 MB  (3.2s)

Output: document_reduced.pdf  (198.4 MB)  — 59.3% smaller  [winner: ghostscript]
```

---

## Web App (Docker)

### Run with Docker Compose

```bash
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080) in your browser.

- Drag-and-drop or click to upload a PDF
- Live progress bar shows each engine running
- The compressed file downloads automatically when done
- Shows original size, compressed size, and % saved

> Large files (500 MB+) can take several minutes. The server timeout is 30 minutes.

### Run with Docker directly

```bash
docker build -t pdf-compressor .
docker run -p 8080:5000 pdf-compressor
```

---

## Desktop App

A standalone PyQt6 application with drag-and-drop support. No Python installation required.

### Build from source

You must build on the target platform (e.g. build on macOS to produce a `.app`).

**macOS / Linux:**
```bash
pip install pyinstaller PyQt6
bash build.sh
```

**Windows:**
```bat
pip install pyinstaller PyQt6
build.bat
```

Output is placed in the `dist/` folder:

| Platform | Output                        |
|----------|-------------------------------|
| macOS    | `dist/PDF Compressor.app`     |
| Linux    | `dist/PDF Compressor`         |
| Windows  | `dist/PDF Compressor.exe`     |

### Ghostscript (optional, recommended)

Ghostscript is not bundled but significantly improves compression. Install it separately:

| Platform | Command                                                                               |
|----------|---------------------------------------------------------------------------------------|
| macOS    | `brew install ghostscript`                                                            |
| Linux    | `sudo apt install ghostscript`                                                        |
| Windows  | Download from [ghostscript.com](https://www.ghostscript.com/releases/gsdnld.html)    |

---

## Architecture

```
pdf_compressor/
├── core/
│   ├── base.py           # CompressionEngine ABC, CompressionResult, CompressionOptions, Preset
│   ├── ghostscript.py    # Ghostscript subprocess engine
│   ├── pikepdf_engine.py # pikepdf + Pillow image recompression engine
│   ├── pypdf_engine.py   # pypdf stream compression engine
│   └── manager.py        # Orchestrates engines, validates outputs, selects best result
├── cli/
│   └── main.py           # argparse CLI entry point (pdf-compressor command)
├── web/
│   ├── app.py            # Flask application factory
│   ├── routes.py         # Upload, job polling, and download endpoints
│   └── templates/
│       └── index.html    # Drag-and-drop UI with live progress bar
├── desktop/
│   └── app.py            # PyQt6 standalone desktop application
└── utils/
    ├── file_utils.py     # File size helpers, safe output path generation
    ├── logging_config.py # Structured logging setup
    └── validation.py     # Input and output PDF validation
```

### How it works

1. **Manager** creates a temp directory and dispatches all enabled engines
2. Each **engine** compresses the input to its own temp file and returns a `CompressionResult`
3. Every successful result is **validated** (pikepdf structural check + magic-byte fallback)
4. The **smallest valid** result is copied to the output path; temp files are cleaned up
5. If no engine beats the original size, the original is copied as the output

---

## Development

### Install development dependencies

```bash
pip install -e ".[dev,web,desktop]"
```

### Run tests

```bash
pytest
pytest --cov=pdf_compressor --cov-report=term-missing
```

### Lint and type-check

```bash
ruff check .
mypy pdf_compressor/
```

---

## Requirements

| Dependency    | Required     | Role                                                |
|---------------|--------------|-----------------------------------------------------|
| `pikepdf`     | Yes          | PDF engine + structural output validation           |
| `pypdf`       | Yes          | PDF engine                                          |
| `Pillow`      | Yes          | Image recompression inside pikepdf engine           |
| `ghostscript` | No           | Best compression; install via OS package manager    |
| `flask`       | Web only     | Web server                                          |
| `gunicorn`    | Web only     | Production WSGI server                              |
| `PyQt6`       | Desktop only | GUI framework                                       |

---

## License

MIT
