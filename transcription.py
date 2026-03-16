import gc
import json
import logging
import os
import queue
import subprocess
import threading

from faster_whisper import WhisperModel
from config import WHISPER_MODEL, HF_TOKEN, PAUSE_THRESHOLD, WEBHOOK_URL
from db import get_db

logger = logging.getLogger(__name__)

# Single serial queue — transcription jobs run one at a time to avoid OOM
transcription_queue = queue.Queue()
transcription_progress = {}  # {recording_id: {"progress": float, "model": str, "started": float}}
notify_progress = False  # toggled by the user via API


def _send_webhook(message):
    """Send a notification via webhook if configured."""
    if not WEBHOOK_URL:
        return
    try:
        import urllib.request
        import urllib.parse
        encoded = urllib.parse.quote(message, safe='')
        url = WEBHOOK_URL.replace("{MESSAGE}", encoded)
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "VoiceTranscriber/1.0")
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.warning(f"Webhook failed: {e}")

_whisper_model = None
_loaded_model_name = None
_model_lock = threading.Lock()
_diarization_pipeline = None
_diarization_lock = threading.Lock()


def _get_or_load_model(model_name=None):
    """Load the model if not already loaded, or swap if a different model is requested."""
    global _whisper_model, _loaded_model_name
    if model_name is None:
        model_name = WHISPER_MODEL
    with _model_lock:
        if _whisper_model is not None and _loaded_model_name != model_name:
            logger.info(f"Swapping model from {_loaded_model_name} to {model_name}...")
            del _whisper_model
            _whisper_model = None
            gc.collect()
        if _whisper_model is None:
            logger.info(f"Loading faster-whisper {model_name} model...")
            _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _loaded_model_name = model_name
            logger.info("Model loaded.")
        return _whisper_model


def _release_memory():
    """Force Python and OS to release freed memory."""
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _unload_model():
    """Unload model to free RAM."""
    global _whisper_model, _loaded_model_name
    with _model_lock:
        if _whisper_model is not None:
            del _whisper_model
            _whisper_model = None
            _loaded_model_name = None
            _release_memory()
            logger.info("Model unloaded, RAM freed.")


def _load_diarization():
    """Load pyannote diarization pipeline."""
    global _diarization_pipeline
    with _diarization_lock:
        if _diarization_pipeline is None:
            from pyannote.audio import Pipeline
            logger.info("Loading diarization pipeline...")
            _diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=HF_TOKEN,
            )
            logger.info("Diarization pipeline loaded.")
        return _diarization_pipeline


def _unload_diarization():
    """Unload diarization pipeline to free RAM."""
    global _diarization_pipeline
    with _diarization_lock:
        if _diarization_pipeline is not None:
            del _diarization_pipeline
            _diarization_pipeline = None
            _release_memory()
            logger.info("Diarization pipeline unloaded.")


def _run_diarization(file_path):
    """Run speaker diarization on an audio file."""
    pipeline = _load_diarization()
    diarization = pipeline(file_path)

    speaker_segments = []
    speaker_map = {}
    counter = 1
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        if speaker not in speaker_map:
            speaker_map[speaker] = f"Speaker {counter}"
            counter += 1
        speaker_segments.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker_map[speaker],
        })
    return speaker_segments


def _format_paragraphs(segments):
    """Group transcription segments into paragraphs based on pauses."""
    if not segments:
        return ""
    paragraphs = []
    current = [segments[0]["text"]]
    for i in range(1, len(segments)):
        gap = segments[i]["start"] - segments[i - 1]["end"]
        if gap >= PAUSE_THRESHOLD:
            paragraphs.append(" ".join(current))
            current = [segments[i]["text"]]
        else:
            current.append(segments[i]["text"])
    paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def _merge_with_speakers(segments, speaker_segments):
    """Merge whisper segments with speaker diarization labels."""
    if not segments:
        return ""

    def get_speaker(start, end):
        best_speaker = "Unknown"
        best_overlap = 0
        for ss in speaker_segments:
            overlap = max(0, min(end, ss["end"]) - max(start, ss["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = ss["speaker"]
        return best_speaker

    for seg in segments:
        seg["speaker"] = get_speaker(seg["start"], seg["end"])

    paragraphs = []
    current_speaker = segments[0]["speaker"]
    current_texts = [segments[0]["text"]]
    for i in range(1, len(segments)):
        gap = segments[i]["start"] - segments[i - 1]["end"]
        if segments[i]["speaker"] != current_speaker or gap >= PAUSE_THRESHOLD:
            paragraphs.append(f"{current_speaker}: {' '.join(current_texts)}")
            current_speaker = segments[i]["speaker"]
            current_texts = [segments[i]["text"]]
        else:
            current_texts.append(segments[i]["text"])
    paragraphs.append(f"{current_speaker}: {' '.join(current_texts)}")
    return "\n\n".join(paragraphs)


def get_audio_duration(file_path):
    """Get duration using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info["format"]["duration"])
    except Exception:
        pass
    return None


def transcribe_audio(file_path, recording_id=None, duration=None, model_name=None, diarize=False):
    """Transcribe an audio file using faster-whisper."""
    import time
    if recording_id:
        transcription_progress[recording_id] = {"progress": 0, "model": model_name or WHISPER_MODEL, "started": time.time()}
    model = _get_or_load_model(model_name)
    segments, info = model.transcribe(file_path, beam_size=5, language="en")
    total_duration = duration or info.duration or 1
    seg_list = []
    last_notified = 0
    for seg in segments:
        if seg.text.strip():
            seg_list.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        if recording_id and total_duration:
            progress_pct = (seg.end / total_duration) * 100
            cap = 80 if diarize else 99
            transcription_progress[recording_id]["progress"] = min(cap, progress_pct)
            if notify_progress:
                pct_int = int(progress_pct)
                if pct_int >= last_notified + 25:
                    last_notified = (pct_int // 25) * 25
                    _send_webhook(f"Progress: {last_notified}% ({model_name or WHISPER_MODEL})")

    logger.info("Transcription done.")

    if diarize and HF_TOKEN:
        _unload_model()
        if recording_id:
            transcription_progress[recording_id]["progress"] = 80
        try:
            speaker_segments = _run_diarization(file_path)
            if recording_id:
                transcription_progress[recording_id]["progress"] = 95
            text = _merge_with_speakers(seg_list, speaker_segments)
        except Exception as e:
            logger.error(f"Diarization failed: {e}, falling back to paragraph format")
            text = _format_paragraphs(seg_list)
        finally:
            _unload_diarization()
    else:
        text = _format_paragraphs(seg_list)

    if recording_id:
        transcription_progress[recording_id]["progress"] = 100
    return text


def _transcribe_recording(recording_id, stored_path, model_name=None, diarize=False):
    """Transcribe a recording and update the database."""
    if model_name is None:
        model_name = WHISPER_MODEL
    conn = get_db()
    row = conn.execute("SELECT display_name, original_filename, duration_seconds FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    name = (row["display_name"] or row["original_filename"]) if row else "Unknown"
    duration = row["duration_seconds"] if row else None
    try:
        conn.execute("UPDATE recordings SET status = 'transcribing' WHERE id = ?", (recording_id,))
        conn.commit()

        _send_webhook(f"Started: {name} ({model_name})")

        if not duration:
            duration = get_audio_duration(stored_path)
        transcript = transcribe_audio(stored_path, recording_id=recording_id, duration=duration, model_name=model_name, diarize=diarize)

        conn.execute(
            "UPDATE recordings SET transcript = ?, duration_seconds = ?, model = ?, status = 'completed', transcribed_at = datetime('now') WHERE id = ?",
            (transcript, duration, model_name, recording_id),
        )
        conn.commit()
        _send_webhook(f"Done: {name} ({model_name})")

    except Exception as e:
        conn.execute(
            "UPDATE recordings SET status = 'failed', transcript = ? WHERE id = ?",
            (str(e), recording_id),
        )
        conn.commit()
    finally:
        transcription_progress.pop(recording_id, None)
        conn.close()


def _queue_worker():
    """Long-running thread that processes transcription jobs serially."""
    while True:
        recording_id, stored_path, model_name, diarize = transcription_queue.get()
        try:
            _transcribe_recording(recording_id, stored_path, model_name, diarize)
        finally:
            transcription_queue.task_done()
            if transcription_queue.empty():
                _unload_model()
                _unload_diarization()


def start_worker():
    """Start the background transcription worker thread."""
    thread = threading.Thread(target=_queue_worker, daemon=True)
    thread.start()


def requeue_incomplete(upload_folder):
    """Re-queue any recordings that need transcription (e.g. after restart)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, stored_filename FROM recordings WHERE status = 'uploaded' AND transcript IS NULL"
    ).fetchall()
    conn.close()
    for row in rows:
        stored_path = os.path.join(upload_folder, row["stored_filename"])
        transcription_queue.put((row["id"], stored_path, WHISPER_MODEL, False))
    if rows:
        logger.info(f"Re-queued {len(rows)} incomplete recording(s) for transcription.")
