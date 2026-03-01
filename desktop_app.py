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

"""PDF Compressor — PyQt6 desktop application.

Standalone GUI wrapper around reduce_size.py.
Compiled with PyInstaller into a single executable for Windows, macOS and Linux.
"""

import os
import sys
import shutil
from pathlib import Path

# When frozen by PyInstaller, add the bundle dir to sys.path so reduce_size
# can be imported.
if getattr(sys, "frozen", False):
    sys.path.insert(0, sys._MEIPASS)  # type: ignore[attr-defined]

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent, QFont, QPainter, QPen, QBrush,
    QDesktopServices,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QFileDialog,
    QFrame, QStackedWidget, QSizePolicy,
)

from reduce_size import (
    compress_ghostscript, compress_pikepdf, compress_pypdf,
    file_size_kb, fmt_size,
)

# ── palette ───────────────────────────────────────────────────────────────────
ACCENT   = "#6366f1"
ACCENT_D = "#4338ca"
SUCCESS  = "#10b981"
SURFACE  = "#f8fafc"
BORDER   = "#e2e8f0"
TEXT     = "#1e1b4b"
MUTED    = "#64748b"

APP_QSS = f"""
QWidget {{
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    color: {TEXT};
    background: white;
}}
QFrame#card {{
    background: white;
    border-radius: 20px;
}}
/* ── drop zone ── */
QFrame#dropZone {{
    border: 2px dashed #c7d2fe;
    border-radius: 14px;
    background: #fafafe;
    min-height: 170px;
}}
QFrame#dropZone[hovered="true"] {{
    border-color: {ACCENT};
    background: #ede9fe;
}}
/* ── buttons ── */
QPushButton {{
    border-radius: 10px;
    font-size: 14px;
    font-weight: 700;
    padding: 10px 24px;
    border: none;
}}
QPushButton#primary {{
    background: {ACCENT};
    color: white;
}}
QPushButton#primary:hover  {{ background: #4f46e5; }}
QPushButton#primary:pressed {{ background: {ACCENT_D}; }}
QPushButton#secondary {{
    background: {SURFACE};
    color: {MUTED};
    border: 1.5px solid {BORDER};
}}
QPushButton#secondary:hover {{ background: #f1f5f9; }}
QPushButton#success {{
    background: {SUCCESS};
    color: white;
}}
QPushButton#success:hover {{ background: #059669; }}
/* ── progress bar ── */
QProgressBar {{
    border-radius: 5px;
    background: #e0e7ff;
    height: 10px;
    text-align: center;
    font-size: 0px;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 #818cf8);
}}
/* ── stat boxes ── */
QFrame#statBox {{
    border-radius: 12px;
    background: {SURFACE};
    border: 1.5px solid {BORDER};
    padding: 4px;
}}
QFrame#statBoxHighlight {{
    border-radius: 12px;
    background: #ecfdf5;
    border: 1.5px solid #6ee7b7;
    padding: 4px;
}}
"""

# ── step configuration ────────────────────────────────────────────────────────
#   step: 0=queued, 1=GS, 2=pikepdf, 3=pypdf, 4=selecting, 5=done
STEP_PCT   = [2, 15, 55, 78, 92, 100]
STEP_LABEL = [
    "Initialising…",
    "Running Ghostscript…",
    "Running pikepdf…",
    "Running pypdf…",
    "Selecting best result…",
    "Done!",
]
STEP_HINT = [
    "Preparing your file…",
    "This pass takes the longest — hang tight.",
    "Recompressing images and streams…",
    "Deduplicating objects…",
    "Comparing all outputs…",
    "",
]


# ── background compression thread ─────────────────────────────────────────────

class CompressionThread(QThread):
    progress = pyqtSignal(int)           # step index
    finished = pyqtSignal(float, float)  # original_kb, compressed_kb
    failed   = pyqtSignal(str)

    def __init__(self, input_path: str, output_path: str):
        super().__init__()
        self.input_path  = input_path
        self.output_path = output_path

    def run(self):
        inp, out = self.input_path, self.output_path
        original_kb = file_size_kb(inp)
        candidates  = []

        try:
            self.progress.emit(1)
            gs = out + ".gs.tmp"
            if compress_ghostscript(inp, gs):
                candidates.append((file_size_kb(gs), gs))

            self.progress.emit(2)
            pk = out + ".pk.tmp"
            if compress_pikepdf(inp, pk):
                candidates.append((file_size_kb(pk), pk))

            self.progress.emit(3)
            py = out + ".py.tmp"
            if compress_pypdf(inp, py):
                candidates.append((file_size_kb(py), py))

            if not candidates:
                self.failed.emit(
                    "No compression engine is available.\n"
                    "Install pikepdf, pypdf, or ghostscript and rebuild."
                )
                return

            self.progress.emit(4)
            best_kb, best_tmp = min(candidates, key=lambda x: x[0])

            for kb, path in candidates:
                if path != best_tmp and os.path.exists(path):
                    os.remove(path)

            if best_kb >= original_kb:
                shutil.copy2(inp, out)
                best_kb = original_kb
            else:
                shutil.move(best_tmp, out)

            self.finished.emit(original_kb, best_kb)

        except Exception as exc:
            # clean up any temp files
            for _, path in candidates:
                if os.path.exists(path):
                    os.remove(path)
            self.failed.emit(str(exc))


# ── custom drop-zone widget ────────────────────────────────────────────────────

class DropZone(QFrame):
    file_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        self.icon_lbl = QLabel("⬆", self)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_lbl.setStyleSheet(f"font-size: 32px; color: {ACCENT};")

        self.main_lbl = QLabel("Drop your PDF here", self)
        self.main_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_lbl.setStyleSheet("font-size: 16px; font-weight: 700;")

        self.sub_lbl = QLabel("or click to browse", self)
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_lbl.setStyleSheet(f"font-size: 12px; color: {MUTED};")

        layout.addWidget(self.icon_lbl)
        layout.addWidget(self.main_lbl)
        layout.addWidget(self.sub_lbl)

    def _set_hovered(self, val: bool):
        self._hovered = val
        self.setProperty("hovered", "true" if val else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith(".pdf"):
                event.acceptProposedAction()
                self._set_hovered(True)

    def dragLeaveEvent(self, event):
        self._set_hovered(False)

    def dropEvent(self, event: QDropEvent):
        self._set_hovered(False)
        path = event.mimeData().urls()[0].toLocalFile()
        if path.lower().endswith(".pdf"):
            self.file_chosen.emit(path)

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF", "", "PDF Files (*.pdf)"
        )
        if path:
            self.file_chosen.emit(path)


# ── stat box helper ────────────────────────────────────────────────────────────

def make_stat_box(label_text: str, highlight: bool = False) -> tuple[QFrame, QLabel]:
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Compressor")
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setAcceptDrops(True)

        self._input_path  = ""
        self._output_path = ""
        self._thread: CompressionThread | None = None

        self._build_ui()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)

        # header
        header = QLabel("PDF Compressor")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(
            f"font-size: 24px; font-weight: 800; color: {TEXT}; margin-bottom: 4px;"
        )
        sub = QLabel("Shrink PDFs using Ghostscript, pikepdf & more.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"font-size: 13px; color: {MUTED}; margin-bottom: 16px;")

        self._stack = QStackedWidget()
        self._stack.addWidget(self._upload_page())
        self._stack.addWidget(self._processing_page())
        self._stack.addWidget(self._result_page())

        outer.addWidget(header)
        outer.addWidget(sub)
        outer.addWidget(self._stack)

    def _upload_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        self._drop_zone = DropZone()
        self._drop_zone.file_chosen.connect(self._on_file_chosen)

        # file chip (hidden until a file is selected)
        self._chip = QLabel()
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chip.setStyleSheet(
            f"background: #ede9fe; color: {ACCENT_D}; border-radius: 99px; "
            f"padding: 6px 14px; font-size: 12px; font-weight: 600;"
        )
        self._chip.hide()

        self._error_lbl = QLabel()
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_lbl.setStyleSheet(
            "background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; "
            "color: #b91c1c; padding: 10px; font-size: 13px;"
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

    def _processing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._proc_title = QLabel("Compressing your PDF…")
        self._proc_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._proc_title.setStyleSheet(
            f"font-size: 17px; font-weight: 700; color: {TEXT};"
        )

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
        self._pct_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {ACCENT};"
        )

        pct_row = QHBoxLayout()
        pct_row.addWidget(
            QLabel("Progress"), alignment=Qt.AlignmentFlag.AlignLeft
        )
        pct_row.addWidget(self._pct_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        for lbl in pct_row.itemAt(0).widget(), :
            lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {MUTED};")

        # step indicators
        self._step_labels: list[QLabel] = []
        steps_layout = QHBoxLayout()
        steps_layout.setSpacing(0)
        step_names = ["Ghostscript", "pikepdf", "pypdf", "Selecting"]
        for i, name in enumerate(step_names):
            col = QVBoxLayout()
            col.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.setSpacing(4)

            dot = QLabel(str(i + 1))
            dot.setFixedSize(28, 28)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setObjectName(f"dot_{i}")
            dot.setStyleSheet(
                "border-radius: 14px; background: #f1f5f9; "
                f"border: 2px solid {BORDER}; font-size: 11px; font-weight: 800; color: #94a3b8;"
            )
            self._step_labels.append(dot)

            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "font-size: 10px; font-weight: 600; color: #cbd5e1; "
                "text-transform: uppercase; letter-spacing: 0.5px;"
            )

            col.addWidget(dot, alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)

            col_widget = QWidget()
            col_widget.setLayout(col)
            steps_layout.addWidget(col_widget)

            if i < len(step_names) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFixedHeight(2)
                line.setStyleSheet(f"background: {BORDER}; margin-bottom: 22px;")
                line.setObjectName(f"conn_{i}")
                steps_layout.addWidget(line, stretch=1)

        layout.addWidget(self._proc_title)
        layout.addWidget(self._proc_hint)
        layout.addSpacing(8)
        layout.addLayout(pct_row)
        layout.addWidget(self._progress_bar)
        layout.addSpacing(8)
        layout.addLayout(steps_layout)
        return page

    def _result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 8, 0, 0)

        tick = QLabel("✓")
        tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tick.setStyleSheet(
            f"font-size: 48px; color: {SUCCESS}; margin-bottom: 4px;"
        )

        done_lbl = QLabel("Done!")
        done_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        done_lbl.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {TEXT};")

        self._result_sub = QLabel("Your compressed file has been saved.")
        self._result_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_sub.setWordWrap(True)
        self._result_sub.setStyleSheet(f"font-size: 13px; color: {MUTED};")

        # stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        box_orig, self._val_orig = make_stat_box("Original")
        box_comp, self._val_comp = make_stat_box("Compressed")
        box_save, self._val_save = make_stat_box("Saved", highlight=True)
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
        layout.addWidget(done_lbl)
        layout.addWidget(self._result_sub)
        layout.addSpacing(4)
        layout.addLayout(stats_row)
        layout.addSpacing(4)
        layout.addWidget(open_btn)
        layout.addWidget(folder_btn)
        layout.addWidget(again_btn)
        return page

    # ── slots ──────────────────────────────────────────────────────────────

    def _on_file_chosen(self, path: str):
        self._input_path = path
        name = Path(path).name
        self._chip.setText(f"📄  {name}")
        self._chip.show()
        self._error_lbl.hide()
        self._compress_btn.show()

    def _start_compression(self):
        if not self._input_path:
            return

        # Ask user where to save
        stem = Path(self._input_path).stem
        default_out = str(Path(self._input_path).parent / f"{stem}_reduced.pdf")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save compressed PDF", default_out, "PDF Files (*.pdf)"
        )
        if not out_path:
            return
        self._output_path = out_path

        self._set_step(0)
        self._stack.setCurrentIndex(1)

        self._thread = CompressionThread(self._input_path, self._output_path)
        self._thread.progress.connect(self._set_step)
        self._thread.finished.connect(self._on_done)
        self._thread.failed.connect(self._on_error)
        self._thread.start()

    def _set_step(self, step: int):
        pct = STEP_PCT[step]
        self._progress_bar.setValue(pct)
        self._pct_lbl.setText(f"{pct}%")
        self._proc_hint.setText(STEP_HINT[step])

        for i, dot in enumerate(self._step_labels):
            s = i + 1  # steps are 1-indexed
            if s < step:
                dot.setStyleSheet(
                    f"border-radius: 14px; background: {ACCENT}; "
                    f"border: 2px solid {ACCENT}; font-size: 11px; font-weight: 800; color: white;"
                )
            elif s == step:
                dot.setStyleSheet(
                    f"border-radius: 14px; background: #ede9fe; "
                    f"border: 2px solid {ACCENT}; font-size: 11px; font-weight: 800; color: {ACCENT};"
                )
            else:
                dot.setStyleSheet(
                    "border-radius: 14px; background: #f1f5f9; "
                    f"border: 2px solid {BORDER}; font-size: 11px; font-weight: 800; color: #94a3b8;"
                )

    def _on_done(self, original_kb: float, compressed_kb: float):
        self._set_step(5)
        reduction = (1 - compressed_kb / original_kb) * 100 if original_kb > 0 else 0
        self._val_orig.setText(fmt_size(original_kb))
        self._val_comp.setText(fmt_size(compressed_kb))
        self._val_save.setText(f"{reduction:.1f}%")
        self._result_sub.setText(f"Saved to: {self._output_path}")
        self._stack.setCurrentIndex(2)

    def _on_error(self, msg: str):
        self._error_lbl.setText(f"Error: {msg}")
        self._error_lbl.show()
        self._stack.setCurrentIndex(0)

    def _open_file(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._output_path))

    def _show_in_folder(self):
        folder = str(Path(self._output_path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _reset(self):
        self._input_path  = ""
        self._output_path = ""
        self._chip.hide()
        self._compress_btn.hide()
        self._error_lbl.hide()
        self._stack.setCurrentIndex(0)

    # allow dropping onto the window itself too
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith(".pdf") and self._stack.currentIndex() == 0:
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        path = event.mimeData().urls()[0].toLocalFile()
        if path.lower().endswith(".pdf"):
            self._on_file_chosen(path)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Compressor")
    app.setStyleSheet(APP_QSS)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
