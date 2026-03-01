"""PDF Compressor — multi-engine PDF size reduction toolkit."""

__version__ = "1.0.0"
__all__ = ["CompressionManager", "CompressionOptions", "CompressionResult", "Preset"]

from pdf_compressor.core.base import CompressionOptions, CompressionResult, Preset
from pdf_compressor.core.manager import CompressionManager
