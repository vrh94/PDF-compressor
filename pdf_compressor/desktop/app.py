"""PyQt6 desktop application for PDF Compressor."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Ensure the package is importable when frozen by PyInstaller
if getattr(sys, "frozen", False):
    sys.path.insert(0, sys._MEIPASS)  # type: ignore[attr-defined]

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QDesktopServices, QUrl
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from pdf_compressor.core.base import CompressionOptions, CompressionResult, Preset
from pdf_compressor.core.manager import CompressionManager
from pdf_compressor.utils.file_utils import file_size_kb, fmt_size

# ── palette ───────────────────────────────────────────────────────────────────
ACCENT   = "#6366f1"
ACCENT_D = "#4338ca"
SUCCESS  = "#10b981"
SURFACE  = "#f8fafc"
BORDER   = "#e2e8f0"
TEXT     = "#1e1b4b"
MUTED    = "#64748b"

APP_QSS = f"""
QWidget {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; color: {TEXT}; background: white; }}
QPushButton {{ border-radius: 10px; font-size: 14px; font-weight: 700; padding: 10px 24px; border: none; }}
QPushButton#primary {{ background: {ACCENT}; color: white; }}
QPushButton#primary:hover {{ background: #4f46e5; }}
QPushButton#primary:pressed {{ background: {ACCENT_D}; }}
QPushButton#secondary {{ background: {SURFACE}; color: {MUTED}; border: 1.5px solid {BORDER}; }}
QPushButton#secondary:hover {{ background: #f1f5f9; }}
QPushButton#success {{ background: {SUCCESS}; color: white; }}
QPushButton#success:hover {{ background: #059669; }}
QProgressBar {{ border-radius: 5px; background: #e0e7ff; height: 10px; font-size: 0px; }}
QProgressBar::chunk {{ border-radius: 5px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {ACCENT},stop:1 #818cf8); }}
QFrame#dropZone {{ border: 2px dashed #c7d2fe; border-radius: 14px; background: #fafafe; min-height: 160px; }}
QFrame#dropZone[hovered="true"] {{ border-color: {ACCENT}; background: #ede9fe; }}
QFrame#statBox {{ border-radius: 12px; background: {SURFACE}; border: 1.5px solid {BORDER}; padding: 4px; }}
QFrame#statBoxHighlight {{ border-radius: 12px; background: #ecfdf5; border: 1.5px solid #6ee7b7; padding: 4px; }}
"""

STEP_PCT   = [2, 15, 55, 78, 92, 100]
STEP_LABEL = ["Initialising…", "Running Ghostscript…", "Running pikepdf…",
              "Running pypdf…", "Selecting best result…", "Done!"]


# ── background thread ─────────────────────────────────────────────────────────

class CompressionThread(QThread):
    step_changed = pyqtSignal(int)
    finished     = pyqtSignal(object, list)   # best_result, all_results
    failed       = pyqtSignal(str)

    def __init__(
        self,
        input_path: str,
        output_path: str,
        options: CompressionOptions,
    ) -> None:
        super().__init__()
        self._input   = input_path
        self._output  = output_path
        self._options = options

    def run(self) -> None:
        try:
            manager = CompressionManager()

            # Wrap engines to emit step signals between runs
            original_engines = manager._engines
            wrapped = _StepEmittingEngines(original_engines, self.step_changed)
            manager._engines = wrapped.engines  # type: ignore[assignment]

            best, all_results = manager.compress(self._input, self._output, self._options)
            self.finished.emit(best, all_results)
        except Exception as exc:
            self.failed.emit(str(exc))


class _StepEmittingEngines:
    """Wraps engine list to emit a Qt signal before each engine run."""

    def __init__(self, engines: list, signal: pyqtSignal) -> None:
        self._signal = signal

        class _WrappedEngine:
            def __init__(self_, eng: object) -> None:
                self_._eng = eng
                self_.name = eng.name  # type: ignore[attr-defined]

            def is_available(self_) -> bool:
                return self_._eng.is_available()  # type: ignore[attr-defined]

            def compress(self_, *args, **kwargs):
                step = ["ghostscript", "pikepdf", "pypdf"].index(self_.name) + 1
                signal.emit(step)
                return self_._eng.compress(*args, **kwargs)  # type: ignore[attr-defined]

        self.engines = [_WrappedEngine(e) for e in engines]


# ── custom drop-zone widget ───────────────────────────────────────────────────

class DropZone(QFrame):
    file_chosen = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        icon = QLabel("⬆")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: 32px; color: {ACCENT};")

        main = QLabel("Drop your PDF here")
        main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main.setStyleSheet("font-size: 16px; font-weight: 700;")

        sub = QLabel("or click to browse")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"font-size: 12px; color: {MUTED};")

        layout.addWidget(icon)
        layout.addWidget(main)
        layout.addWidget(sub)

    def _set_hovered(self, val: bool) -> None:
        self._hovered = val
        self.setProperty("hovered", "true" if val else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith(".pdf"):
                event.acceptProposedAction()
                self._set_hovered(True)

    def dragLeaveEvent(self, event) -> None:
        self._set_hovered(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_hovered(False)
        path = event.mimeData().urls()[0].toLocalFile()
        if path.lower().endswith(".pdf"):
            self.file_chosen.emit(path)

    def mousePressEvent(self, event) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF Files (*.pdf)")
        if path:
            self.file_chosen.emit(path)


# ── stat box helper ───────────────────────────────────────────────────────────

def _make_stat_box(label_text: str, highlight: bool = False) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("statBoxHighlight" if highlight else "statBox")
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(3)

    lbl = QLabel(label_text)
    lbl.setStyleSheet(
        f"font-size: 10px; font-weight: 700; text-transform: uppercase; "
        f"letter-spacing: 1px; color: {'#059669' if highlight else MUTED};"
    )
    val = QLabel("—")
    val.setStyleSheet(
        f"font-size: 18px; font-weight: 800; "
        f"color: {'#047857' if highlight else TEXT};"
    )
    layout.addWidget(lbl)
    layout.addWidget(val)
    return frame, val


# ── main window ───────────────────────────────────────────────────────────────

class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF Compressor")
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setAcceptDrops(True)

        self._input_path  = ""
        self._output_path = ""
        self._thread: Optional[CompressionThread] = None
        self._step_dots: list[QLabel] = []

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)

        header = QLabel("PDF Compressor")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {TEXT};")

        sub = QLabel("Shrink PDFs using Ghostscript, pikepdf & more.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"font-size: 13px; color: {MUTED}; margin-bottom: 8px;")

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_upload_page())
        self._stack.addWidget(self._build_processing_page())
        self._stack.addWidget(self._build_result_page())

        outer.addWidget(header)
        outer.addWidget(sub)
        outer.addWidget(self._stack)

    def _build_upload_page(self) -> QWidget:
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        self._drop_zone = DropZone()
        self._drop_zone.file_chosen.connect(self._on_file_chosen)

        self._chip = QLabel()
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chip.setStyleSheet(
            f"background:#ede9fe;color:{ACCENT_D};border-radius:99px;"
            "padding:6px 14px;font-size:12px;font-weight:600;"
        )
        self._chip.hide()

        self._error_lbl = QLabel()
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_lbl.setStyleSheet(
            "background:#fef2f2;border:1px solid #fecaca;border-radius:10px;"
            "color:#b91c1c;padding:10px;font-size:13px;"
        )
        self._error_lbl.hide()

        self._compress_btn = QPushButton("Compress PDF")
        self._compress_btn.setObjectName("primary")
        self._compress_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._compress_btn.clicked.connect(self._start_compression)
        self._compress_btn.hide()

        layout.addWidget(self._drop_zone)
        layout.addWidget(self._chip)
        layout.addWidget(self._error_lbl)
        layout.addWidget(self._compress_btn)
        return page

    def _build_processing_page(self) -> QWidget:
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Compressing your PDF…")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {TEXT};")

        self._proc_hint = QLabel("Initialising…")
        self._proc_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._proc_hint.setStyleSheet(f"font-size: 12px; color: {MUTED};")

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(10)
        self._progress_bar.setTextVisible(False)

        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._pct_lbl.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {ACCENT};")

        pct_row = QHBoxLayout()
        prog_lbl = QLabel("Progress")
        prog_lbl.setStyleSheet(f"font-size: 12px; color: {MUTED};")
        pct_row.addWidget(prog_lbl)
        pct_row.addWidget(self._pct_lbl)

        # Step indicator dots
        steps_layout = QHBoxLayout()
        steps_layout.setSpacing(0)
        step_names = ["Ghostscript", "pikepdf", "pypdf", "Selecting"]
        self._step_dots = []
        for i, name in enumerate(step_names):
            col = QVBoxLayout()
            col.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.setSpacing(4)

            dot = QLabel(str(i + 1))
            dot.setFixedSize(28, 28)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet(
                f"border-radius:14px;background:#f1f5f9;"
                f"border:2px solid {BORDER};font-size:11px;font-weight:800;color:#94a3b8;"
            )
            self._step_dots.append(dot)

            name_lbl = QLabel(name)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet(
                "font-size:10px;font-weight:600;color:#cbd5e1;"
                "text-transform:uppercase;letter-spacing:0.5px;"
            )
            col.addWidget(dot, alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(name_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

            col_w = QWidget()
            col_w.setLayout(col)
            steps_layout.addWidget(col_w)

            if i < len(step_names) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFixedHeight(2)
                line.setStyleSheet(f"background:{BORDER};margin-bottom:22px;")
                steps_layout.addWidget(line, stretch=1)

        layout.addWidget(title)
        layout.addWidget(self._proc_hint)
        layout.addSpacing(8)
        layout.addLayout(pct_row)
        layout.addWidget(self._progress_bar)
        layout.addSpacing(8)
        layout.addLayout(steps_layout)
        return page

    def _build_result_page(self) -> QWidget:
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 8, 0, 0)

        tick = QLabel("✓")
        tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tick.setStyleSheet(f"font-size: 48px; color: {SUCCESS};")

        done = QLabel("Done!")
        done.setAlignment(Qt.AlignmentFlag.AlignCenter)
        done.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {TEXT};")

        self._result_sub = QLabel("Your compressed file has been saved.")
        self._result_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_sub.setWordWrap(True)
        self._result_sub.setStyleSheet(f"font-size: 13px; color: {MUTED};")

        self._result_detail = QLabel()
        self._result_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_detail.setStyleSheet(f"font-size: 11px; color: {MUTED};")

        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        box_orig, self._val_orig = _make_stat_box("Original")
        box_comp, self._val_comp = _make_stat_box("Compressed")
        box_save, self._val_save = _make_stat_box("Saved", highlight=True)
        stats_row.addWidget(box_orig)
        stats_row.addWidget(box_comp)
        stats_row.addWidget(box_save)

        open_btn = QPushButton("Open file")
        open_btn.setObjectName("success")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._open_file)

        folder_btn = QPushButton("Show in folder")
        folder_btn.setObjectName("secondary")
        folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_btn.clicked.connect(self._show_in_folder)

        again_btn = QPushButton("Compress another file")
        again_btn.setObjectName("secondary")
        again_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        again_btn.clicked.connect(self._reset)

        layout.addWidget(tick)
        layout.addWidget(done)
        layout.addWidget(self._result_sub)
        layout.addWidget(self._result_detail)
        layout.addSpacing(4)
        layout.addLayout(stats_row)
        layout.addSpacing(4)
        layout.addWidget(open_btn)
        layout.addWidget(folder_btn)
        layout.addWidget(again_btn)
        return page

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_file_chosen(self, path: str) -> None:
        self._input_path = path
        self._chip.setText(f"📄  {Path(path).name}")
        self._chip.show()
        self._error_lbl.hide()
        self._compress_btn.show()

    def _start_compression(self) -> None:
        if not self._input_path:
            return
        stem = Path(self._input_path).stem
        default = str(Path(self._input_path).parent / f"{stem}_reduced.pdf")
        out, _ = QFileDialog.getSaveFileName(self, "Save compressed PDF", default, "PDF Files (*.pdf)")
        if not out:
            return
        self._output_path = out

        self._set_step(0)
        self._stack.setCurrentIndex(1)

        options = CompressionOptions(preset=Preset.MEDIUM, threads=1)
        self._thread = CompressionThread(self._input_path, self._output_path, options)
        self._thread.step_changed.connect(self._set_step)
        self._thread.finished.connect(self._on_done)
        self._thread.failed.connect(self._on_error)
        self._thread.start()

    def _set_step(self, step: int) -> None:
        pct = STEP_PCT[min(step, len(STEP_PCT) - 1)]
        self._progress_bar.setValue(pct)
        self._pct_lbl.setText(f"{pct}%")
        self._proc_hint.setText(STEP_LABEL[min(step, len(STEP_LABEL) - 1)])

        for i, dot in enumerate(self._step_dots):
            s = i + 1
            if s < step:
                dot.setStyleSheet(
                    f"border-radius:14px;background:{ACCENT};"
                    f"border:2px solid {ACCENT};font-size:11px;font-weight:800;color:white;"
                )
            elif s == step:
                dot.setStyleSheet(
                    f"border-radius:14px;background:#ede9fe;"
                    f"border:2px solid {ACCENT};font-size:11px;font-weight:800;color:{ACCENT};"
                )
            else:
                dot.setStyleSheet(
                    f"border-radius:14px;background:#f1f5f9;"
                    f"border:2px solid {BORDER};font-size:11px;font-weight:800;color:#94a3b8;"
                )

    def _on_done(self, best: CompressionResult, all_results: list) -> None:
        self._set_step(5)
        orig_kb = best.original_size / 1024
        comp_kb = best.compressed_size / 1024
        pct = best.reduction_pct
        self._val_orig.setText(fmt_size(orig_kb))
        self._val_comp.setText(fmt_size(comp_kb))
        self._val_save.setText(f"{pct:.1f}%")
        self._result_sub.setText(f"Winner: {best.engine_name}")
        self._result_detail.setText(f"Saved to: {self._output_path}")

        # Show per-engine breakdown
        details = []
        for r in all_results:
            if r.success:
                details.append(f"{r.engine_name}: {fmt_size(r.compressed_size / 1024)} ({r.duration:.1f}s)")
            else:
                details.append(f"{r.engine_name}: failed")
        self._result_detail.setToolTip("\n".join(details))

        self._stack.setCurrentIndex(2)

    def _on_error(self, msg: str) -> None:
        self._error_lbl.setText(f"Error: {msg}")
        self._error_lbl.show()
        self._stack.setCurrentIndex(0)

    def _open_file(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._output_path))

    def _show_in_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._output_path).parent)))

    def _reset(self) -> None:
        self._input_path = ""
        self._output_path = ""
        self._chip.hide()
        self._compress_btn.hide()
        self._error_lbl.hide()
        self._stack.setCurrentIndex(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self._stack.currentIndex() == 0:
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith(".pdf"):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        path = event.mimeData().urls()[0].toLocalFile()
        if path.lower().endswith(".pdf"):
            self._on_file_chosen(path)


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Compressor")
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
