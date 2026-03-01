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

"""
Reduce PDF file size as much as possible.
Usage: python3 reduce_size.py input.pdf [output.pdf]
"""

import sys
import os
import subprocess
import shutil
import io
from pathlib import Path


def fmt_size(kb: float) -> str:
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb:.1f} KB"


def file_size_kb(path):
    return os.path.getsize(path) / 1024


def compress_ghostscript(input_path: str, output_path: str) -> bool:
    """
    Compress using Ghostscript — best overall compression.
    Tries progressively more aggressive settings and keeps the smallest result.
    """
    if not shutil.which("gs"):
        return False

    best_path = None
    best_size = float("inf")

    settings = [
        ("/ebook", 150),  # good quality, moderate compression
        ("/screen", 72),  # aggressive: low dpi, small file
    ]

    for pdf_setting, dpi in settings:
        tmp = output_path + f".gs_{dpi}.tmp"
        cmd = [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={pdf_setting}",
            # Force downsampling — without these gs may skip rescaling
            "-dDownsampleColorImages=true",
            "-dDownsampleGrayImages=true",
            "-dDownsampleMonoImages=true",
            "-dColorImageDownsampleType=/Bicubic",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dColorImageDownsampleThreshold=1.0",
            "-dGrayImageDownsampleThreshold=1.0",
            f"-dColorImageResolution={dpi}",
            f"-dGrayImageResolution={dpi}",
            f"-dMonoImageResolution={min(dpi * 2, 300)}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
            f"-sOutputFile={tmp}",
            input_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=1800)  # 30 min
            if result.returncode == 0 and os.path.exists(tmp):
                size = file_size_kb(tmp)
                if size < best_size:
                    if best_path and os.path.exists(best_path):
                        os.remove(best_path)
                    best_size = size
                    best_path = tmp
                else:
                    os.remove(tmp)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            if os.path.exists(tmp):
                os.remove(tmp)

    if best_path:
        shutil.move(best_path, output_path)
        return True
    return False


def compress_pikepdf(input_path: str, output_path: str) -> bool:
    """
    Compress using pikepdf: stream compression + object stream packing.
    Also recompresses images with Pillow where possible.
    """
    try:
        import pikepdf
    except ImportError:
        return False

    try:
        with pikepdf.open(input_path) as pdf:
            _recompress_images(pdf)
            pdf.save(
                output_path,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                recompress_flate=True,
            )
        return True
    except Exception as e:
        print(f"  pikepdf error: {e}", file=sys.stderr)
        return False


def _recompress_images(pdf):
    """Downscale and JPEG-compress large raster images inside the PDF."""
    try:
        import pikepdf  # noqa: F401 — confirms pikepdf is available before iterating
    except ImportError:
        return

    MAX_DIM = 1200   # cap image width/height — aggressive but readable
    JPEG_QUALITY = 60  # lower quality = much smaller images

    for page in pdf.pages:
        try:
            resources = page.get("/Resources")
            if not resources:
                continue
            xobjects = resources.get("/XObject")
            if not xobjects:
                continue
            for key in list(xobjects.keys()):
                try:
                    xobj = xobjects[key]
                    if xobj.get("/Subtype") != "/Image":
                        continue
                    # Skip masks and 1-bit images
                    bits = int(xobj.get("/BitsPerComponent", 8))
                    if bits < 8:
                        continue
                    _recompress_one_image(xobj, MAX_DIM, JPEG_QUALITY)
                except Exception:
                    pass
        except Exception:
            pass


def _recompress_one_image(xobj, max_dim: int, quality: int):
    from PIL import Image
    import pikepdf

    pil_img = None

    # Try reading as a PIL image directly from compressed data
    try:
        raw = bytes(xobj.read_raw_bytes())
        pil_img = Image.open(io.BytesIO(raw))
        pil_img.load()
    except Exception:
        pil_img = None

    # Fall back to uncompressed pixel data
    if pil_img is None:
        try:
            width = int(xobj["/Width"])
            height = int(xobj["/Height"])
            cs = str(xobj.get("/ColorSpace", "/DeviceRGB"))
            mode_map = {"/DeviceRGB": ("RGB", 3), "/DeviceGray": ("L", 1)}
            if cs not in mode_map:
                return
            mode, _ = mode_map[cs]
            raw = bytes(xobj.read_bytes())
            pil_img = Image.frombytes(mode, (width, height), raw)
        except Exception:
            return

    # Flatten transparency
    if pil_img.mode in ("RGBA", "LA", "P"):
        pil_img = pil_img.convert("RGB")
    elif pil_img.mode == "L":
        pass  # keep grayscale
    elif pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")

    # Downscale if large
    if max(pil_img.width, pil_img.height) > max_dim:
        ratio = max_dim / max(pil_img.width, pil_img.height)
        new_size = (int(pil_img.width * ratio), int(pil_img.height * ratio))
        pil_img = pil_img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)

    xobj.write(buf.getvalue(), filter=pikepdf.Name("/DCTDecode"))
    xobj["/Width"] = pil_img.width
    xobj["/Height"] = pil_img.height
    xobj["/ColorSpace"] = pikepdf.Name(
        "/DeviceRGB" if pil_img.mode == "RGB" else "/DeviceGray"
    )
    xobj["/BitsPerComponent"] = 8


def compress_pypdf(input_path: str, output_path: str) -> bool:
    """Basic fallback: compress content streams with pypdf."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return False

    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for page in reader.pages:
            page.compress_content_streams()
            writer.add_page(page)
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        with open(output_path, "wb") as f:
            writer.write(f)
        return True
    except Exception as e:
        print(f"  pypdf error: {e}", file=sys.stderr)
        return False


def reduce(input_path: str, output_path: str):
    original_size = file_size_kb(input_path)
    print(f"Input:  {input_path}  ({fmt_size(original_size)})")
    print("  (Large files can take several minutes per strategy — please wait)")

    candidates = []  # list of (size_kb, path)

    # --- Strategy 1: Ghostscript ---
    gs_out = output_path + ".gs.tmp"
    print("  Trying Ghostscript...", end=" ", flush=True)
    if compress_ghostscript(input_path, gs_out):
        sz = file_size_kb(gs_out)
        print(fmt_size(sz))
        candidates.append((sz, gs_out))
    else:
        print("not available")

    # --- Strategy 2: pikepdf + image recompression ---
    pk_out = output_path + ".pk.tmp"
    print("  Trying pikepdf...", end=" ", flush=True)
    if compress_pikepdf(input_path, pk_out):
        sz = file_size_kb(pk_out)
        print(fmt_size(sz))
        candidates.append((sz, pk_out))
    else:
        print("not available")

    # --- Strategy 3: pypdf fallback ---
    py_out = output_path + ".py.tmp"
    print("  Trying pypdf...", end=" ", flush=True)
    if compress_pypdf(input_path, py_out):
        sz = file_size_kb(py_out)
        print(fmt_size(sz))
        candidates.append((sz, py_out))
    else:
        print("not available")

    if not candidates:
        print("ERROR: No compression library available.", file=sys.stderr)
        print("Install at least one of: ghostscript, pikepdf, pypdf", file=sys.stderr)
        sys.exit(1)

    # Pick the smallest result
    best_size, best_tmp = min(candidates, key=lambda x: x[0])

    # Clean up losers
    for sz, path in candidates:
        if path != best_tmp and os.path.exists(path):
            os.remove(path)

    if best_size >= original_size:
        os.remove(best_tmp)
        print(f"\nCould not reduce size (best attempt: {fmt_size(best_size)} >= {fmt_size(original_size)}).")
        print("Copying original to output.")
        shutil.copy2(input_path, output_path)
    else:
        shutil.move(best_tmp, output_path)
        reduction = (1 - best_size / original_size) * 100
        print(f"\nOutput: {output_path}  ({fmt_size(best_size)})  — {reduction:.1f}% smaller")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 reduce_size.py input.pdf [output.pdf]")
        sys.exit(1)

    input_path = sys.argv[1]

    if not os.path.isfile(input_path):
        print(f"ERROR: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not input_path.lower().endswith(".pdf"):
        print("WARNING: File does not have a .pdf extension, proceeding anyway.")

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        p = Path(input_path)
        output_path = str(p.with_stem(p.stem + "_reduced"))

    if os.path.abspath(input_path) == os.path.abspath(output_path):
        print("ERROR: Input and output paths must be different.", file=sys.stderr)
        sys.exit(1)

    reduce(input_path, output_path)


if __name__ == "__main__":
    main()
