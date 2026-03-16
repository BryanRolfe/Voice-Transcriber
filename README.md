# 🎙️ Voice Transcriber

A self-hosted web app for uploading audio recordings and transcribing them with AI. Works as a full **iPhone PWA** — add it to your Home Screen for a native app feel.

---

## ✨ Features

- 📤 **Upload multiple recordings at once** — drag & drop or tap to select
- 🤖 **AI transcription** — powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with selectable models (tiny → large-v3)
- 🎛️ **Model selector** — choose between speed and accuracy per recording
- 🗣️ **Speaker diarization** — optional speaker identification via [pyannote.audio](https://github.com/pyannote/pyannote-audio) (requires HuggingFace token)
- 📊 **Live progress bar** — real-time transcription progress with percentage
- 🎵 **Custom audio player** — sleek dark-themed player with seek bar
- ✏️ **Rename recordings** — editable names that persist across sessions
- 📋 **Copy transcripts** — one tap to copy to clipboard
- 🔁 **Re-transcribe** — redo any recording with a different model (shown on button)
- ☑️ **Multi-select** — select multiple recordings to batch re-transcribe or delete
- 🔒 **Password protection** — optional session-based auth via environment variable
- 🃏 **Card layout** — expandable cards with lazy-loaded transcripts, audio player, and actions
- 📱 **iPhone Web App (PWA)** — installable, dark theme, safe-area aware, pull to refresh
- � **Webhook notifications** — optional push notifications on transcription start, completion, and progress
- �🐳 **Docker** — fully containerized with persistent storage

---

## 📋 Supported Formats

`WAV` · `MP3` · `M4A` · `OGG` · `FLAC` · `WebM` · `AAC` · `WMA` · `QTA`

All formats are automatically converted for both transcription and browser playback via FFmpeg.

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- An SSH key for your target server

### 1. Clone the repo

```bash
git clone https://github.com/BryanRolfe/Voice-Transcriber.git
cd Voice-Transcriber
```

### 2. Configure deployment

```bash
cp .env.example .env
```

Edit `.env`:

```env
DEPLOY_HOST=your.server.ip
DEPLOY_USER=your_username
DEPLOY_PATH=/home/your_username/transcriber
DEPLOY_PORT=1337
APP_PASSWORD=your_password_here    # optional, omit to disable auth
SECRET_KEY=your_random_secret      # optional, auto-generated if omitted
HF_TOKEN=hf_your_token_here        # optional, needed for speaker diarization
WEBHOOK_URL=https://example.com/?message={MESSAGE}  # optional, webhook notifications
```

### 3. Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

> ⚠️ The first build downloads the ~1.5GB faster-whisper medium.en model — expect several minutes depending on your connection.

The app will be live at **http://your-server:1337**

---

## 📱 iPhone Installation

1. Open **http://your-server:1337** in **Safari**
2. Tap the **Share** button ↑
3. Tap **"Add to Home Screen"**
4. Done — it launches like a native app 🎉

---

## 🏗️ Architecture

```
┌─────────────────────────────────────┐
│           Docker Container           │
│                                     │
│  Flask + Gunicorn  (:1337)          │
│  ├── faster-whisper (medium.en default)│
│  ├── pyannote.audio (optional)      │
│  └── FFmpeg (format conversion)     │
│                                     │
│  /data  (persistent volume)         │
│  ├── uploads/   ← original files    │
│  └── transcriber.db  ← SQLite      │
└─────────────────────────────────────┘
```

### Project Structure

```
app.py              ← Flask routes & app factory
config.py           ← Environment variables & constants
db.py               ← SQLite database helpers
auth.py             ← Authentication blueprint
audio.py            ← Audio streaming & transcoding
transcription.py    ← Whisper model management & queue worker
static/             ← Frontend assets (CSS, JS, PWA)
templates/          ← HTML templates
```

| Layer | Tech |
|-------|------|
| Backend | Python / Flask / Gunicorn |
| Transcription | faster-whisper (int8, CPU) |
| Diarization | pyannote.audio 3.1 (optional) |
| Audio | FFmpeg |
| Database | SQLite (WAL mode) |
| Frontend | Vanilla HTML/CSS/JS |
| PWA | Web App Manifest + Service Worker |
| Container | Docker + Compose |

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `UPLOAD_FOLDER` | `/data/uploads` | Where original files are stored |
| `DB_PATH` | `/data/transcriber.db` | SQLite database path |
| `APP_PASSWORD` | *(none)* | Set to enable password protection |
| `SECRET_KEY` | *(auto)* | Flask session secret |
| `HF_TOKEN` | *(none)* | HuggingFace token for speaker diarization |
| `WEBHOOK_URL` | *(none)* | Webhook URL for notifications (use `{MESSAGE}` as placeholder) |
| `WHISPER_MODEL` | `medium.en` | Default transcription model |

---

## 🎛️ Available Models

| Model | Speed | Accuracy | RAM |
|-------|-------|----------|-----|
| `tiny.en` | ⚡⚡⚡ | ★☆☆ | ~75MB |
| `small.en` | ⚡⚡ | ★★☆ | ~460MB |
| `medium.en` | ⚡ | ★★★ | ~1.5GB |
| `large-v3` | 🐢 | ★★★★ | ~3GB |

Select the model from the dropdown before uploading or re-transcribing.

---

## 🗂️ API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/recordings` | List all recordings |
| `GET` | `/api/recordings/:id` | Get recording details |
| `POST` | `/api/upload` | Upload audio file(s) |
| `POST` | `/api/recordings/:id/rename` | Rename a recording |
| `POST` | `/api/recordings/:id/retranscribe` | Re-transcribe with model selection |
| `POST` | `/api/recordings/batch/retranscribe` | Batch re-transcribe selected recordings |
| `POST` | `/api/recordings/batch/delete` | Batch delete selected recordings |
| `POST` | `/api/retranscribe-all` | Re-transcribe all recordings |
| `DELETE` | `/api/recordings/:id` | Delete a recording |
| `GET` | `/api/recordings/:id/audio` | Stream audio (range requests supported) |
| `GET` | `/api/models` | List available models |
| `POST` | `/api/notifications/toggle` | Toggle progress webhook notifications |

---

## 💾 Persistence

Data is stored in a named Docker volume (`transcriber-data`) mounted at `/data`. It survives:
- ✅ Container restarts
- ✅ `docker compose up --build` (rebuilds)
- ❌ `docker volume rm transcriber-data` (don't do this unless you want to wipe everything)

The container is configured with `restart: unless-stopped` so it comes back automatically after a server reboot.

---

## 🖥️ Server Requirements

| Resource | Minimum | Notes |
|----------|---------|-------|
| CPU | 2 cores | N95 or better works fine |
| RAM | 4 GB | Large model peaks ~3GB |
| Disk | 10 GB | Models + uploads |
| GPU | Not required | Runs entirely on CPU |

---

## 📝 License

MIT
