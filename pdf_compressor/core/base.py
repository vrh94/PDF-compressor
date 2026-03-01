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

"""Abstract base classes and shared data structures for all compression engines."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Preset(str, Enum):
    """Named compression presets ordered from most to least aggressive."""

    LOW = "low"       # 72 dpi, JPEG q=50  — smallest file, visible quality loss
    MEDIUM = "medium" # 150 dpi, JPEG q=72 — balanced default
    HIGH = "high"     # 200 dpi, JPEG q=85 — good quality, moderate compression
    LOSSLESS = "lossless"  # 300 dpi, JPEG q=95 — minimal loss, largest output


#: Per-preset engine parameters.  Individual CLI flags can override these.
PRESET_CONFIGS: dict[Preset, dict] = {
    Preset.LOW: {
        "dpi": 72,
        "jpeg_quality": 50,
        "gs_setting": "/screen",
        "max_image_dim": 1000,
    },
    Preset.MEDIUM: {
        "dpi": 150,
        "jpeg_quality": 72,
        "gs_setting": "/ebook",
        "max_image_dim": 1200,
    },
    Preset.HIGH: {
        "dpi": 200,
        "jpeg_quality": 85,
        "gs_setting": "/printer",
        "max_image_dim": 1600,
    },
    Preset.LOSSLESS: {
        "dpi": 300,
        "jpeg_quality": 95,
        "gs_setting": "/prepress",
        "max_image_dim": 4000,
    },
}


@dataclass
class CompressionOptions:
    """Runtime options passed to every engine and the manager."""

    preset: Preset = Preset.MEDIUM

    # Override individual preset parameters (None = use preset default)
    dpi: Optional[int] = None
    jpeg_quality: Optional[int] = None

    keep_temp: bool = False   # retain intermediate temp files
    verbose: bool = False
    threads: int = 1          # >1 enables parallel engine execution

    # Engine filter: None = use all available
    engines: Optional[list[str]] = field(default=None)

    def resolved_dpi(self) -> int:
        return self.dpi or PRESET_CONFIGS[self.preset]["dpi"]

    def resolved_jpeg_quality(self) -> int:
        return self.jpeg_quality or PRESET_CONFIGS[self.preset]["jpeg_quality"]

    def resolved_gs_setting(self) -> str:
        return PRESET_CONFIGS[self.preset]["gs_setting"]

    def resolved_max_image_dim(self) -> int:
        return PRESET_CONFIGS[self.preset]["max_image_dim"]


@dataclass
class CompressionResult:
    """Outcome of a single engine run."""

    success: bool
    engine_name: str
    original_size: int = 0     # bytes
    compressed_size: int = 0   # bytes
    output_path: str = ""
    error_message: str = ""
    duration: float = 0.0      # seconds

    @property
    def reduction_pct(self) -> float:
        """Percentage reduction relative to the original."""
        if self.original_size == 0:
            return 0.0
        return (1 - self.compressed_size / self.original_size) * 100

    @property
    def is_smaller(self) -> bool:
        """True when the compressed output is actually smaller than the input."""
        return self.success and self.compressed_size < self.original_size

    def __repr__(self) -> str:
        if self.success:
            return (
                f"<CompressionResult engine={self.engine_name!r} "
                f"reduction={self.reduction_pct:.1f}% "
                f"duration={self.duration:.1f}s>"
            )
        return f"<CompressionResult engine={self.engine_name!r} FAILED: {self.error_message!r}>"


class CompressionEngine(ABC):
    """
    Abstract base class for every compression strategy.

    Implementations must:
    - Never raise from ``compress()``; encode failures in ``CompressionResult``.
    - Write the result to *output_path* on success.
    - Be stateless and thread-safe.
    """

    #: Human-readable engine identifier used in logs and results.
    name: str = "base"

    def is_available(self) -> bool:
        """Return True when this engine's runtime dependencies are present."""
        return True

    @abstractmethod
    def compress(
        self,
        input_path: str,
        output_path: str,
        options: CompressionOptions,
    ) -> CompressionResult:
        """Compress *input_path* and write the result to *output_path*."""

    # ── helpers ──────────────────────────────────────────────────────────────

    def _fail(
        self,
        original_size: int,
        message: str,
        start: float = 0.0,
    ) -> CompressionResult:
        return CompressionResult(
            success=False,
            engine_name=self.name,
            original_size=original_size,
            error_message=message,
            duration=time.perf_counter() - start if start else 0.0,
        )

    def _success(
        self,
        original_size: int,
        compressed_size: int,
        output_path: str,
        start: float,
    ) -> CompressionResult:
        return CompressionResult(
            success=True,
            engine_name=self.name,
            original_size=original_size,
            compressed_size=compressed_size,
            output_path=output_path,
            duration=time.perf_counter() - start,
        )
