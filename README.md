# yt-dlp Manager

A beautiful, cross-platform web UI for **yt-dlp** — download videos and audio from YouTube and 1800+ other sites.

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue)

## Features

- 🎯 **Paste & Go** — paste any URL, see video info instantly
- ⚡ **Quick Presets** — one-click download in Best, 1080p, 720p, 480p, MP3, or M4A
- 🎛️ **Advanced Formats** — browse and download any available format
- 📊 **Real-time Progress** — live download speed, ETA, and progress bar via WebSocket
- 🌙 **Stunning Dark UI** — glassmorphism design with smooth animations
- 🖥️ **Cross-platform** — works on macOS, Windows, and Linux

## Prerequisites

- **Python 3.9+** — [python.org](https://www.python.org/downloads/)
- **ffmpeg** (recommended) — needed for merging video+audio and format conversion
  - macOS: `brew install ffmpeg`
  - Windows: `choco install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html)
  - Linux: `sudo apt install ffmpeg`

## Quick Start

```bash
# Clone or navigate to the project
cd yt-dlp-manager

# Run the app (auto-installs dependencies)
python run.py
```

The app will:
1. Install any missing Python packages (`fastapi`, `uvicorn`, `yt-dlp`)
2. Start the server on `http://127.0.0.1:8899`
3. Open your browser automatically

## Project Structure

```
yt-dlp-manager/
├── run.py                  # Cross-platform launcher
├── backend/
│   ├── __init__.py
│   ├── server.py           # FastAPI server (REST + WebSocket)
│   └── requirements.txt    # Python dependencies
├── frontend/
│   ├── index.html          # Main page
│   ├── style.css           # Dark glassmorphism theme
│   └── app.js              # Frontend logic
├── downloads/              # Default download directory (auto-created)
└── README.md
```

## How It Works

1. **Paste a URL** into the input field
2. **Click "Fetch Info"** — the server uses yt-dlp's Python API to extract metadata and available formats
3. **Pick a preset** (one-click) or expand **Advanced Formats** to choose a specific stream
4. **Watch the progress** — real-time updates via WebSocket
5. **Open the downloads folder** when done

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/info?url=...` | GET | Fetch video metadata and formats |
| `/api/downloads-dir` | GET | Get the downloads directory path |
| `/api/open-downloads` | POST | Open downloads folder in file manager |
| `/ws/download` | WebSocket | Stream download with real-time progress |

## License

MIT
