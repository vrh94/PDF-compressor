# PDF Compressor

Reduce PDF file size as aggressively as possible. Available as a **command-line tool**, a **Docker web app**, and a **standalone desktop app** for Windows, macOS and Linux.

All three modes run up to three compression strategies and automatically keep the smallest result:

| Strategy | Technique | Requires |
|---|---|---|
| **Ghostscript** | Re-renders at lower DPI with Bicubic downsampling | `ghostscript` |
| **pikepdf** | Stream compression + image recompression via Pillow | `pikepdf`, `Pillow` |
| **pypdf** | Content stream compression + duplicate object removal | `pypdf` |

---

## Desktop App (Windows / macOS / Linux)

Standalone GUI — no Python installation required.

### Build

You must build on the target platform (e.g. build on macOS to get a `.app`).

**macOS / Linux**
```bash
bash build.sh
```

**Windows**
```bat
build.bat
```

Output is placed in the `dist/` folder:

| Platform | Output |
|---|---|
| macOS | `dist/PDF Compressor.app` |
| Linux | `dist/PDF Compressor` |
| Windows | `dist/PDF Compressor.exe` |

### Features
- Drag & drop or browse to select a PDF
- Choose where to save the output
- Real-time progress bar with per-engine step indicators
- Shows original size, compressed size, and % saved
- "Open file" and "Show in folder" buttons on completion

### Ghostscript (optional, recommended)
Ghostscript is not bundled but significantly improves compression. Install it separately on the user's machine:

| Platform | Command |
|---|---|
| macOS | `brew install ghostscript` |
| Linux | `sudo apt install ghostscript` |
| Windows | Download from [ghostscript.com](https://www.ghostscript.com/releases/gsdnld.html) |

---

## Web App (Docker)

### Requirements
- [Docker](https://docs.docker.com/get-docker/)

### Run

```bash
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080) in your browser.

### Features
- Drag & drop or click to upload a PDF
- Real-time progress bar (polls compression status every 1.5 s)
- Download starts automatically when done
- Shows original size, compressed size, and % saved

> Large files (500 MB+) can take several minutes. The server timeout is set to 30 minutes.

---

## Command-Line

### Requirements

```bash
# Ghostscript (macOS)
brew install ghostscript

# Python libraries
pip3 install pikepdf Pillow pypdf
```

### Usage

```bash
# Output auto-named <filename>_reduced.pdf
python3 reduce_size.py document.pdf

# Explicit output path
python3 reduce_size.py document.pdf output.pdf
```

### Example output

```
Input:  document.pdf  (487.3 MB)
  (Large files can take several minutes per strategy — please wait)
  Trying Ghostscript...  198.4 MB
  Trying pikepdf...      312.1 MB
  Trying pypdf...        481.0 MB

Output: document_reduced.pdf  (198.4 MB)  — 59.3% smaller
```

---

## Project Structure

```
.
├── reduce_size.py       # Core compression logic (shared by all modes)
├── app.py               # Flask web server
├── desktop_app.py       # PyQt6 desktop application
├── desktop_app.spec     # PyInstaller build configuration
├── build.sh             # Desktop build script — macOS / Linux
├── build.bat            # Desktop build script — Windows
├── templates/
│   └── index.html       # Web UI
├── Dockerfile
├── docker-compose.yml
└── requirements.txt     # Web app Python dependencies
```
