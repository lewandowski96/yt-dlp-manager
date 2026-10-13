"""
yt-dlp Manager — Backend Server
FastAPI server with WebSocket progress streaming for yt-dlp operations.
"""

import asyncio
import json
import os
import platform
import threading
import uuid
from pathlib import Path
from queue import Queue
from typing import Optional

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
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Track active downloads: download_id -> { thread, queue, cancel_event }
active_downloads: dict = {}

# ---------- Serve Frontend ----------
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ---------- REST Endpoints ----------

@app.get("/api/info")
async def get_video_info(url: str):
    """Fetch video metadata and available formats without downloading."""
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if info is None:
            return JSONResponse(
                status_code=400,
                content={"error": "Could not extract video information."},
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
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


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
async def get_downloads_dir():
    """Return the current downloads directory."""
    return {"path": str(DOWNLOADS_DIR)}


@app.post("/api/open-downloads")
async def open_downloads_folder():
    """Open the downloads folder in the system file manager."""
    path = str(DOWNLOADS_DIR)
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

        def run_download():
            try:
                ydl_opts = {
                    "format": format_str,
                    "outtmpl": str(DOWNLOADS_DIR / "%(title)s.%(ext)s"),
                    "progress_hooks": [progress_hook],
                    "postprocessor_hooks": [postprocessor_hook],
                    "quiet": True,
                    "no_warnings": True,
                    "merge_output_format": "mp4",
                }
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
                    "error": str(e),
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
