"""pikepdf-based compression engine with Pillow image recompression."""

from __future__ import annotations

import io
import os
import time
from typing import TYPE_CHECKING

from pdf_compressor.core.base import (
    CompressionEngine,
    CompressionOptions,
    CompressionResult,
)
from pdf_compressor.utils.logging_config import get_logger

if TYPE_CHECKING:
    pass  # avoid heavy imports at module level

log = get_logger(__name__)

# pikepdf color-space → PIL mode mapping
_CS_TO_MODE: dict[str, tuple[str, int]] = {
    "/DeviceRGB":  ("RGB",  3),
    "/DeviceGray": ("L",    1),
}


class PikepdfEngine(CompressionEngine):
    """
    Compression via pikepdf (QPDF bindings).

    Applies:
    - Flate stream recompression
    - Object-stream packing
    - JPEG recompression + downscaling of large raster images (via Pillow)
    """

    name = "pikepdf"

    def is_available(self) -> bool:
        try:
            import pikepdf  # noqa: F401
            return True
        except ImportError:
            return False

    def compress(
        self,
        input_path: str,
        output_path: str,
        options: CompressionOptions,
    ) -> CompressionResult:
        start = time.perf_counter()
        try:
            original_size = os.path.getsize(input_path)
        except OSError as exc:
            return self._fail(0, f"Cannot read input file: {exc}", start)

        try:
            import pikepdf
        except ImportError:
            return self._fail(original_size, "pikepdf is not installed.", start)

        try:
            with pikepdf.open(input_path) as pdf:
                _recompress_images(pdf, options)
                pdf.save(
                    output_path,
                    compress_streams=True,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                    recompress_flate=True,
                )
        except Exception as exc:
            log.debug("pikepdf error: %s", exc)
            return self._fail(original_size, str(exc), start)

        if not os.path.exists(output_path):
            return self._fail(original_size, "pikepdf produced no output file.", start)

        return self._success(
            original_size, os.path.getsize(output_path), output_path, start
        )


# ── image recompression helpers ───────────────────────────────────────────────

def _recompress_images(pdf: object, options: CompressionOptions) -> None:
    """Walk all pages and recompress oversized raster images with Pillow."""
    try:
        from PIL import Image  # noqa: F401
        import pikepdf
    except ImportError:
        log.debug("Pillow not available — skipping image recompression.")
        return

    max_dim = options.resolved_max_image_dim()
    quality = options.resolved_jpeg_quality()

    for page in pdf.pages:  # type: ignore[attr-defined]
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
                    if int(xobj.get("/BitsPerComponent", 8)) < 8:
                        continue  # skip 1-bit masks
                    if _is_already_small_jpeg(xobj, max_dim):
                        continue  # skip already-compact JPEGs
                    _recompress_one_image(xobj, max_dim, quality)
                except Exception as exc:
                    log.debug("Skipping image %s: %s", key, exc)
        except Exception as exc:
            log.debug("Skipping page: %s", exc)


def _is_already_small_jpeg(xobj: object, max_dim: int) -> bool:
    """Return True when the image is JPEG-encoded and fits within max_dim."""
    try:
        import pikepdf
        filters = xobj.get("/Filter")
        if filters is None:
            return False
        filter_name = str(filters)
        if "/DCTDecode" not in filter_name:
            return False
        w = int(xobj["/Width"])
        h = int(xobj["/Height"])
        return max(w, h) <= max_dim
    except Exception:
        return False


def _recompress_one_image(xobj: object, max_dim: int, quality: int) -> None:
    """Re-encode a single PDF image object as JPEG at the given quality."""
    from PIL import Image
    import pikepdf

    pil_img: Image.Image | None = None

    # Attempt 1: decode from existing compressed stream
    try:
        raw = bytes(xobj.read_raw_bytes())  # type: ignore[attr-defined]
        pil_img = Image.open(io.BytesIO(raw))
        pil_img.load()
    except Exception:
        pil_img = None

    # Attempt 2: decode uncompressed pixel data
    if pil_img is None:
        try:
            cs = str(xobj.get("/ColorSpace", "/DeviceRGB"))
            if cs not in _CS_TO_MODE:
                return
            mode, _ = _CS_TO_MODE[cs]
            w = int(xobj["/Width"])
            h = int(xobj["/Height"])
            raw = bytes(xobj.read_bytes())  # type: ignore[attr-defined]
            pil_img = Image.frombytes(mode, (w, h), raw)
        except Exception:
            return

    # Normalise to RGB or grayscale for JPEG
    if pil_img.mode in ("RGBA", "LA", "P"):
        pil_img = pil_img.convert("RGB")
    elif pil_img.mode not in ("RGB", "L"):
        pil_img = pil_img.convert("RGB")

    # Downscale if too large
    if max(pil_img.width, pil_img.height) > max_dim:
        ratio = max_dim / max(pil_img.width, pil_img.height)
        pil_img = pil_img.resize(
            (int(pil_img.width * ratio), int(pil_img.height * ratio)),
            Image.LANCZOS,
        )

    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)

    xobj.write(buf.getvalue(), filter=pikepdf.Name("/DCTDecode"))  # type: ignore[attr-defined]
    xobj["/Width"] = pil_img.width
    xobj["/Height"] = pil_img.height
    xobj["/ColorSpace"] = pikepdf.Name(  # type: ignore[attr-defined]
        "/DeviceRGB" if pil_img.mode == "RGB" else "/DeviceGray"
    )
    xobj["/BitsPerComponent"] = 8
