from pathlib import Path


ROOT = Path(SPECPATH).parent
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR")
if not (TESSERACT / "tesseract.exe").is_file():
    raise SystemExit("No se encuentra Tesseract en C:\\Program Files\\Tesseract-OCR")

analysis = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(TESSERACT), "tesseract")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="OptimizadorFacturaElectrica",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="OptimizadorFacturaElectrica",
)
