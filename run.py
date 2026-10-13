#!/usr/bin/env python3
"""
yt-dlp Manager — Cross-platform launcher.
Starts the FastAPI backend and opens the browser.
"""

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8899
URL = f"http://{HOST}:{PORT}"

BASE_DIR = Path(__file__).resolve().parent


def check_dependencies():
    """Ensure required Python packages are installed."""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import yt_dlp  # noqa: F401
    except ImportError:
        print("📦  Installing dependencies...")
        req_file = BASE_DIR / "backend" / "requirements.txt"
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
        )


def main():
    check_dependencies()

    # Import after ensuring deps are installed
    import uvicorn

    print(f"\n🚀  yt-dlp Manager starting at {URL}")
    print("   Press Ctrl+C to stop.\n")

    # Open browser after a short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(URL)

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        "backend.server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
