"""
yt-dlp Manager — Backend Server
FastAPI server with WebSocket progress streaming for yt-dlp operations.
"""

import asyncio
import json
import os
import platform
import re
import shutil
import string
import threading
import uuid
from pathlib import Path
from queue import Queue
from typing import Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="yt-dlp Manager", version="1.0.0")

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Paths ----------
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
CONFIG_FILE = BASE_DIR / "config.json"
DEFAULT_DOWNLOADS_DIR = BASE_DIR / "downloads"


def _load_config() -> dict:
    """Load config from disk, returning defaults if missing."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_config(config: dict):
    """Persist config to disk."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_downloads_dir() -> Path:
    """Return the configured downloads directory, falling back to default."""
    config = _load_config()
    path_str = config.get("downloads_dir")
    if path_str:
        p = Path(path_str)
        if p.is_dir():
            return p
    DEFAULT_DOWNLOADS_DIR.mkdir(exist_ok=True)
    return DEFAULT_DOWNLOADS_DIR


def get_cookie_opts() -> dict:
    """Return yt-dlp cookie and JS runtime options based on current config."""
    config = _load_config()
    source = config.get("cookie_source", "chrome").lower()
    opts = {}
    if source in ("chrome", "firefox", "safari", "brave", "edge", "opera", "vivaldi", "chromium"):
        opts["cookiesfrombrowser"] = (source,)
    elif source == "file":
        cookie_file = config.get("cookie_file", "")
        if cookie_file and Path(cookie_file).is_file():
            opts["cookiefile"] = cookie_file

    # Enable node JS runtime if node is installed (required for YouTube n-challenge solving)
    if shutil.which("node"):
        opts["js_runtimes"] = {"node": {}}
    return opts


# Track active downloads: download_id -> { thread, queue, cancel_event }
active_downloads: dict = {}

# ---------- Serve Frontend ----------
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


def is_playlist_url(url: str) -> bool:
    """Check if a URL refers purely to a playlist rather than a single video."""
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
        qs = parse_qs(parsed.query)

        # YouTube pure playlist
        if "playlist" in path:
            return True

        # YouTube URL with list= but no single video identifier
        if "list" in qs and "v" not in qs:
            parts = [p for p in path.split("/") if p]
            # youtu.be shortlink might have video in path like youtu.be/<id>?list=...
            if parsed.netloc.endswith("youtu.be") and parts:
                return False
            return True

        if "/playlists" in path:
            return True
    except Exception:
        pass
    return False


def clean_error_message(err: str, url: str = "") -> str:
    """Convert raw yt-dlp error output into user-friendly messages."""
    err_lower = err.lower()

    if is_playlist_url(url) or "playlist" in err_lower:
        return "Playlist links are not yet supported. Please paste the link to an individual video."

    if "please sign in" in err_lower or "cookies" in err_lower:
        if "list=" in url:
            return "Playlist links are not yet supported. Please paste the link to an individual video."
        return "This video requires signing in. Select your browser in the [COOKIES] menu in the header to authenticate."

    if "could not copy" in err_lower and "cookies database" in err_lower:
        return "Could not read cookies from the selected browser. Please make sure the browser is installed and closed to unlock its database."

    if "requested format is not available" in err_lower:
        return "The requested format is not available for this video. Please try another quality option."

    if "video unavailable" in err_lower or "this video is unavailable" in err_lower:
        return "This video is unavailable. It may have been removed or made private."

    if "unable to download webpage" in err_lower or "connection refused" in err_lower:
        return "Could not connect to the video host. Please check your network connection and URL."

    # Strip raw CLI formatting like 'ERROR: [youtube] id: '
    cleaned = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*([^:]+:\s*)?)?", "", err).strip()
    cleaned = re.sub(r"See https?://\S+", "", cleaned).strip()
    return cleaned if cleaned else err


# ---------- REST Endpoints ----------

@app.get("/api/info")
async def get_video_info(url: str):
    """Fetch video metadata and available formats without downloading."""
    url = url.strip()
    if is_playlist_url(url):
        return JSONResponse(
            status_code=400,
            content={"error": "Playlist links are not yet supported. Please paste the link to an individual video."},
        )

    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": "in_playlist",
        }
        ydl_opts.update(get_cookie_opts())
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if info is None:
            return JSONResponse(
                status_code=400,
                content={"error": "Could not extract video information."},
            )

        # Check if the extracted result is a playlist
        if info.get("_type") == "playlist" or ("entries" in info and not info.get("formats")):
            return JSONResponse(
                status_code=400,
                content={"error": "Playlist links are not yet supported. Please paste the link to an individual video."},
            )

        # Build clean format list
        formats = []
        seen = set()
        for f in info.get("formats", []):
            fmt_id = f.get("format_id", "")
            ext = f.get("ext", "")
            resolution = f.get("resolution", "audio only")
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0
            fps = f.get("fps")
            tbr = f.get("tbr")  # total bitrate
            format_note = f.get("format_note", "")

            has_video = vcodec != "none"
            has_audio = acodec != "none"

            # Determine type
            if has_video and has_audio:
                fmt_type = "video+audio"
            elif has_video:
                fmt_type = "video"
            else:
                fmt_type = "audio"

            key = (fmt_id, ext)
            if key in seen:
                continue
            seen.add(key)

            formats.append({
                "format_id": fmt_id,
                "ext": ext,
                "resolution": resolution,
                "fps": fps,
                "filesize": filesize,
                "tbr": tbr,
                "type": fmt_type,
                "vcodec": vcodec if has_video else None,
                "acodec": acodec if has_audio else None,
                "format_note": format_note,
            })

        # Quick‑pick presets
        presets = _build_presets(info)

        thumbnail = info.get("thumbnail") or info.get("thumbnails", [{}])[-1].get("url")

        return {
            "title": info.get("title", "Unknown"),
            "channel": info.get("channel") or info.get("uploader", "Unknown"),
            "duration": info.get("duration"),
            "thumbnail": thumbnail,
            "webpage_url": info.get("webpage_url", url),
            "formats": formats,
            "presets": presets,
        }

    except yt_dlp.utils.DownloadError as e:
        return JSONResponse(status_code=400, content={"error": clean_error_message(str(e), url)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": clean_error_message(str(e), url)})


def _build_presets(info: dict) -> list[dict]:
    """Build user-friendly download presets."""
    presets = []

    # Best video + audio
    presets.append({
        "id": "best",
        "label": "Best Quality",
        "description": "Best video + audio merged",
        "format_str": "bestvideo+bestaudio/best",
        "icon": "⭐",
    })

    # 1080p
    presets.append({
        "id": "1080p",
        "label": "1080p",
        "description": "Full HD video + audio",
        "format_str": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "icon": "🎬",
    })

    # 720p
    presets.append({
        "id": "720p",
        "label": "720p",
        "description": "HD video + audio",
        "format_str": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "icon": "📺",
    })

    # 480p
    presets.append({
        "id": "480p",
        "label": "480p",
        "description": "SD video + audio",
        "format_str": "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "icon": "📱",
    })

    # Audio only (MP3)
    presets.append({
        "id": "audio_mp3",
        "label": "Audio (MP3)",
        "description": "Best audio → MP3",
        "format_str": "bestaudio/best",
        "icon": "🎵",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    })

    # Audio only (M4A / AAC)
    presets.append({
        "id": "audio_m4a",
        "label": "Audio (M4A)",
        "description": "Best audio → M4A",
        "format_str": "bestaudio[ext=m4a]/bestaudio/best",
        "icon": "🎶",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
            "preferredquality": "192",
        }],
    })

    return presets


@app.get("/api/downloads-dir")
async def api_get_downloads_dir():
    """Return the current downloads directory."""
    return {"path": str(get_downloads_dir())}


@app.post("/api/downloads-dir")
async def api_set_downloads_dir(body: dict):
    """Set a new downloads directory. Body: { "path": "/some/path" }"""
    new_path = body.get("path", "").strip()
    if not new_path:
        return JSONResponse(status_code=400, content={"error": "Path is required."})

    p = Path(new_path)
    if not p.exists():
        # Try to create it
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return JSONResponse(status_code=400, content={"error": f"Cannot create directory: {e}"})
    elif not p.is_dir():
        return JSONResponse(status_code=400, content={"error": "Path is not a directory."})

    config = _load_config()
    config["downloads_dir"] = str(p.resolve())
    _save_config(config)
    return {"path": str(p.resolve())}


@app.get("/api/cookies")
async def api_get_cookies():
    """Return the configured cookie source."""
    config = _load_config()
    return {
        "source": config.get("cookie_source", "chrome"),
        "file": config.get("cookie_file", ""),
    }


@app.post("/api/cookies")
async def api_set_cookies(body: dict):
    """Set the cookie source (e.g. 'chrome', 'firefox', 'none', 'file')."""
    source = body.get("source", "none").strip().lower()
    file_path = body.get("file", "").strip()
    valid_sources = ("none", "chrome", "firefox", "safari", "brave", "edge", "opera", "vivaldi", "chromium", "file")
    if source not in valid_sources:
        return JSONResponse(status_code=400, content={"error": f"Invalid cookie source: {source}"})

    if source == "file" and file_path:
        p = Path(file_path)
        if not p.is_file():
            return JSONResponse(status_code=400, content={"error": "Cookie file not found."})

    config = _load_config()
    config["cookie_source"] = source
    if file_path:
        config["cookie_file"] = file_path
    elif source != "file":
        config.pop("cookie_file", None)
    _save_config(config)

    return {"status": "ok", "source": source, "file": config.get("cookie_file", "")}


@app.get("/api/browse")
async def api_browse_directory(path: str = ""):
    """
    List directories inside a given path for the directory browser modal.
    Returns parent path and list of child directories.
    """
    try:
        if not path:
            # Start from the user's home directory
            target = Path.home()
        else:
            target = Path(path)

        if not target.exists() or not target.is_dir():
            return JSONResponse(status_code=400, content={"error": "Directory not found."})

        parent = str(target.parent) if target.parent != target else None

        dirs = []
        try:
            for entry in sorted(target.iterdir()):
                # Skip hidden files/dirs and non-directories
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    dirs.append({
                        "name": entry.name,
                        "path": str(entry),
                    })
        except PermissionError:
            pass

        # On Windows, provide drive letters as root options
        drives = None
        if platform.system() == "Windows" and (not path or target == target.parent):
            drives = []
            for letter in string.ascii_uppercase:
                drive = Path(f"{letter}:\\")
                if drive.exists():
                    drives.append({"name": f"{letter}:\\", "path": str(drive)})

        return {
            "current": str(target),
            "parent": parent,
            "directories": dirs,
            "drives": drives,
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/open-downloads")
async def open_downloads_folder():
    """Open the downloads folder in the system file manager."""
    path = str(get_downloads_dir())
    system = platform.system()
    try:
        if system == "Darwin":
            os.system(f'open "{path}"')
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            os.system(f'xdg-open "{path}"')
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------- WebSocket Download ----------

@app.websocket("/ws/download")
async def websocket_download(ws: WebSocket):
    """
    Accepts a WebSocket connection. Client sends a JSON message to start download:
    {
        "url": "...",
        "format_str": "bestvideo+bestaudio/best",
        "postprocessors": [...],   // optional
    }
    Server streams progress events back as JSON.
    """
    await ws.accept()
    try:
        raw = await ws.receive_text()
        request = json.loads(raw)
        url = request["url"]
        format_str = request.get("format_str", "bestvideo+bestaudio/best")
        postprocessors = request.get("postprocessors", [])

        download_id = str(uuid.uuid4())[:8]
        progress_queue: Queue = Queue()
        cancel_event = threading.Event()

        def progress_hook(d):
            if cancel_event.is_set():
                raise yt_dlp.utils.DownloadError("Download cancelled by user.")
            if d["status"] == "downloading":
                progress_queue.put({
                    "type": "progress",
                    "download_id": download_id,
                    "status": "downloading",
                    "percent": d.get("_percent_str", "0%").strip(),
                    "speed": d.get("_speed_str", "N/A").strip(),
                    "eta": d.get("_eta_str", "N/A").strip(),
                    "downloaded": d.get("downloaded_bytes", 0),
                    "total": d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                    "filename": os.path.basename(d.get("filename", "")),
                })
            elif d["status"] == "finished":
                progress_queue.put({
                    "type": "progress",
                    "download_id": download_id,
                    "status": "post_processing",
                    "filename": os.path.basename(d.get("filename", "")),
                })

        def postprocessor_hook(d):
            if d["status"] == "started":
                progress_queue.put({
                    "type": "progress",
                    "download_id": download_id,
                    "status": "post_processing",
                    "postprocessor": d.get("postprocessor", ""),
                })
            elif d["status"] == "finished":
                progress_queue.put({
                    "type": "progress",
                    "download_id": download_id,
                    "status": "post_processing_done",
                })

        download_dir = get_downloads_dir()

        def run_download():
            try:
                ydl_opts = {
                    "format": format_str,
                    "outtmpl": str(download_dir / "%(title)s.%(ext)s"),
                    "progress_hooks": [progress_hook],
                    "postprocessor_hooks": [postprocessor_hook],
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "merge_output_format": "mp4",
                }
                ydl_opts.update(get_cookie_opts())
                if postprocessors:
                    ydl_opts["postprocessors"] = postprocessors

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                progress_queue.put({
                    "type": "complete",
                    "download_id": download_id,
                    "status": "complete",
                })
            except Exception as e:
                progress_queue.put({
                    "type": "error",
                    "download_id": download_id,
                    "status": "error",
                    "error": clean_error_message(str(e), url),
                })

        # Start download in background thread
        thread = threading.Thread(target=run_download, daemon=True)
        active_downloads[download_id] = {
            "thread": thread,
            "queue": progress_queue,
            "cancel_event": cancel_event,
        }

        await ws.send_json({
            "type": "started",
            "download_id": download_id,
            "status": "started",
        })

        thread.start()

        # Stream progress to client
        while True:
            # Check for cancel messages from client (non-blocking)
            try:
                client_msg = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
                msg = json.loads(client_msg)
                if msg.get("action") == "cancel":
                    cancel_event.set()
                    await ws.send_json({
                        "type": "cancelled",
                        "download_id": download_id,
                        "status": "cancelled",
                    })
                    break
            except asyncio.TimeoutError:
                pass

            # Drain the progress queue
            while not progress_queue.empty():
                event = progress_queue.get_nowait()
                await ws.send_json(event)

                if event["type"] in ("complete", "error"):
                    # Clean up
                    active_downloads.pop(download_id, None)
                    return

            await asyncio.sleep(0.2)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        # Clean up if download was active
        for did, info in list(active_downloads.items()):
            info["cancel_event"].set()
        active_downloads.clear()


# ---------- Run ----------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8899, log_level="info")
