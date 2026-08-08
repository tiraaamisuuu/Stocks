from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


project_root = Path(SPEC).resolve().parent
datas = [
    (str(project_root / "app.py"), "."),
    (str(project_root / ".streamlit" / "config.toml"), ".streamlit"),
    (str(project_root / "data" / "trader_signals.csv"), "data"),
]
binaries = []
hiddenimports = collect_submodules("paperalpha")

# Streamlit executes app.py dynamically, so its imports are not visible from the
# launcher entry point. Collect these runtime packages and their data explicitly.
for package in (
    "streamlit",
    "plotly",
    "yfinance",
    "vaderSentiment",
    "pandas_market_calendars",
    "exchange_calendars",
    "scipy",
):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

analysis = Analysis(
    [str(project_root / "launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="PaperAlpha",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / "packaging" / "windows_version.txt"),
)
