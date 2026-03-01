# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for PDF Compressor desktop app.
#
# Build commands (run from the project root):
#   macOS / Linux:  pyinstaller desktop_app.spec
#   Windows:        pyinstaller desktop_app.spec
#
# Output:
#   macOS  →  dist/PDF Compressor.app   (drag to /Applications)
#   Windows→  dist/PDF Compressor.exe
#   Linux  →  dist/PDF Compressor       (ELF binary)

from PyInstaller.utils.hooks import collect_all, collect_data_files

# Collect everything needed for pikepdf (QPDF bindings, data, hidden imports)
pikepdf_d, pikepdf_b, pikepdf_h = collect_all("pikepdf")
pypdf_d,   pypdf_b,   pypdf_h   = collect_all("pypdf")
pil_d,     pil_b,     pil_h     = collect_all("PIL")

a = Analysis(
    ["desktop_app.py"],
    pathex=[],
    binaries=pikepdf_b + pil_b + pypdf_b,
    datas=(
        pikepdf_d + pil_d + pypdf_d
        + [("reduce_size.py", ".")]   # bundle the compression module
    ),
    hiddenimports=(
        pikepdf_h + pil_h + pypdf_h
        + [
            "pikepdf._core",
            "PIL.Image",
            "PIL.ImageFile",
            "PIL.JpegImagePlugin",
            "pypdf",
            "pypdf.generic",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ── platform-specific packaging ───────────────────────────────────────────────
import sys

if sys.platform == "darwin":
    # macOS: produce a .app bundle
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="PDF Compressor",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="PDF Compressor",
    )
    app = BUNDLE(
        coll,
        name="PDF Compressor.app",
        bundle_identifier="com.pdfcompressor.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
            "NSRequiresAquaSystemAppearance": False,  # support dark mode
        },
    )

else:
    # Windows / Linux: single-file executable
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="PDF Compressor",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,           # compress the exe (install upx for smaller output)
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,       # no terminal window
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
