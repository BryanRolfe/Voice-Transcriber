import os
import secrets

# Paths
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/data/uploads")
DB_PATH = os.environ.get("DB_PATH", "/data/transcriber.db")
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB

# Auth
APP_PASSWORD = os.environ.get("APP_PASSWORD")

# Transcription
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium.en")
HF_TOKEN = os.environ.get("HF_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PAUSE_THRESHOLD = 1.5  # seconds of silence to trigger paragraph break

ALLOWED_EXTENSIONS = {"wav", "mp3", "ogg", "m4a", "flac", "webm", "mp4", "aac", "wma", "qta"}

AVAILABLE_MODELS = [
    {"id": "tiny.en", "name": "Tiny", "description": "Fastest, lowest accuracy (~75MB RAM)"},
    {"id": "small.en", "name": "Small", "description": "Fast, decent accuracy (~460MB RAM)"},
    {"id": "medium.en", "name": "Medium", "description": "Balanced speed & accuracy (~1.5GB RAM)"},
    {"id": "large-v3", "name": "Large v3", "description": "Best accuracy, slowest (~3GB RAM)"},
]
