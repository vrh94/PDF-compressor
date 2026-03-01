#!/usr/bin/env bash
# Build the PDF Compressor desktop app on macOS or Linux.
# Run from the project root:  bash build.sh
set -e

echo "==> Installing Python dependencies…"
pip install pyinstaller pyqt6 pikepdf Pillow pypdf

echo "==> Building with PyInstaller…"
pyinstaller desktop_app.spec --clean --noconfirm

if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "==> macOS build complete."
    echo "    App bundle: dist/PDF Compressor.app"
    echo "    To distribute: zip -r 'PDF_Compressor_macOS.zip' 'dist/PDF Compressor.app'"
    echo ""
    echo "    NOTE: Ghostscript is NOT bundled. For maximum compression,"
    echo "    tell users to install it:  brew install ghostscript"
else
    echo "==> Linux build complete."
    echo "    Executable: dist/PDF Compressor"
    echo ""
    echo "    NOTE: Ghostscript is NOT bundled. For maximum compression,"
    echo "    tell users to install it:  sudo apt install ghostscript"
fi
