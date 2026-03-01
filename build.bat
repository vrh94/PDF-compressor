@echo off
REM Build the PDF Compressor desktop app on Windows.
REM Run from the project root:  build.bat

echo =^> Installing Python dependencies...
pip install pyinstaller pyqt6 pikepdf Pillow pypdf

echo =^> Building with PyInstaller...
pyinstaller desktop_app.spec --clean --noconfirm

echo.
echo =^> Windows build complete.
echo     Executable: dist\PDF Compressor.exe
echo.
echo     NOTE: Ghostscript is NOT bundled. For maximum compression,
echo     tell users to download and install it from:
echo     https://www.ghostscript.com/releases/gsdnld.html
echo.
pause
