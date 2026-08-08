from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def _available_port(preferred: int = 8501) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
        except OSError:
            probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _open_browser_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(url, timeout=1):
                break
        except Exception:
            time.sleep(0.25)
    else:
        return

    if os.environ.get("PAPERALPHA_NO_BROWSER") == "1":
        return
    # PyInstaller adjusts Windows' DLL search path. Clear that process-level
    # override before asking the operating system to launch an external browser.
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    webbrowser.open(url)


def main() -> None:
    from streamlit.web import cli as streamlit_cli

    bundle_dir = Path(__file__).resolve().parent
    app_path = bundle_dir / "app.py"
    if not app_path.exists():
        raise FileNotFoundError(f"Bundled dashboard was not found: {app_path}")

    requested_port = int(os.environ.get("PAPERALPHA_PORT", "8501"))
    port = _available_port(requested_port)
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
    ]
    streamlit_cli.main()


def _show_startup_error(exc: Exception) -> None:
    message = f"PaperAlpha could not start.\n\n{type(exc).__name__}: {exc}"
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, message, "PaperAlpha", 0x10)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        _show_startup_error(error)
        raise
