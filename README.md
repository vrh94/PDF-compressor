# PDF Compressor

A tool to reduce PDF file size as aggressively as possible, available both as a **command-line script** and a **Docker web app**.

It runs up to three compression strategies in parallel and automatically keeps the smallest result:

| Strategy | Technique | Requires |
|---|---|---|
| **Ghostscript** | Re-renders the PDF at lower DPI with Bicubic downsampling | `ghostscript` |
| **pikepdf** | Stream compression + image recompression via Pillow | `pikepdf`, `Pillow` |
| **pypdf** | Content stream compression + duplicate object removal | `pypdf` |

---

## Web App (Docker)

### Requirements
- [Docker](https://docs.docker.com/get-docker/)

### Run

```bash
docker build -t pdf-compressor .
docker run -p 5000:5000 pdf-compressor
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

**Features:**
- Drag & drop or click to upload a PDF
- Compression runs server-side (Ghostscript + pikepdf + pypdf)
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
├── reduce_size.py      # Core compression logic (CLI entry point)
├── app.py              # Flask web server
├── templates/
│   └── index.html      # Upload UI
├── Dockerfile
└── requirements.txt
```
