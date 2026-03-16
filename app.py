import os
import uuid
import logging

from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename

from config import (
    UPLOAD_FOLDER, SECRET_KEY, MAX_CONTENT_LENGTH,
    ALLOWED_EXTENSIONS, AVAILABLE_MODELS, WHISPER_MODEL, HF_TOKEN, WEBHOOK_URL,
)
from db import get_db, init_db
from auth import auth_bp, login_required
from audio import get_web_audio_path, stream_file
import transcription as transcription_mod
from transcription import (
    transcription_queue, transcription_progress,
    start_worker, requeue_incomplete,
)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["SECRET_KEY"] = SECRET_KEY

app.register_blueprint(auth_bp)

logger = logging.getLogger(__name__)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/models", methods=["GET"])
@login_required
def get_models():
    return jsonify({
        "models": AVAILABLE_MODELS,
        "default": WHISPER_MODEL,
        "diarization_available": bool(HF_TOKEN),
        "notifications_available": bool(WEBHOOK_URL),
        "notify_progress": transcription_mod.notify_progress,
    })


@app.route("/api/notifications/toggle", methods=["POST"])
@login_required
def toggle_notifications():
    transcription_mod.notify_progress = not transcription_mod.notify_progress
    return jsonify({"notify_progress": transcription_mod.notify_progress})


@app.route("/api/upload", methods=["POST"])
@login_required
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": f"File type not allowed. Supported: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    recording_id = str(uuid.uuid4())
    original_filename = secure_filename(file.filename) or "recording"

    if "." in original_filename:
        ext = original_filename.rsplit(".", 1)[1].lower()
    else:
        ext = file.filename.rsplit(".", 1)[1].lower() if "." in (file.filename or "") else "wav"
        original_filename = f"{original_filename}.{ext}"

    stored_filename = f"{recording_id}.{ext}"
    stored_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    file.save(stored_path)
    file_size = os.path.getsize(stored_path)

    conn = get_db()
    conn.execute(
        "INSERT INTO recordings (id, original_filename, stored_filename, file_size, status) VALUES (?, ?, ?, ?, ?)",
        (recording_id, original_filename, stored_filename, file_size, "uploaded"),
    )
    conn.commit()
    conn.close()

    model_name = request.form.get("model", WHISPER_MODEL)
    if model_name not in [m["id"] for m in AVAILABLE_MODELS]:
        model_name = WHISPER_MODEL
    diarize = request.form.get("diarize", "false").lower() == "true"
    transcription_queue.put((recording_id, stored_path, model_name, diarize))

    return jsonify({"id": recording_id, "status": "processing"}), 201


@app.route("/api/recordings", methods=["GET"])
@login_required
def list_recordings():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, original_filename, display_name, file_size, duration_seconds, "
        "transcript, model, status, created_at, transcribed_at "
        "FROM recordings ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    recordings = []
    for row in rows:
        transcript = row["transcript"] or ""
        rec = {
            "id": row["id"],
            "original_filename": row["original_filename"],
            "display_name": row["display_name"],
            "file_size": row["file_size"],
            "duration_seconds": row["duration_seconds"],
            "transcript_preview": transcript[:200],
            "model": row["model"],
            "status": row["status"],
            "created_at": row["created_at"],
            "transcribed_at": row["transcribed_at"],
        }
        if row["id"] in transcription_progress:
            p = transcription_progress[row["id"]]
            rec["progress"] = round(p["progress"], 1)
            rec["transcribing_model"] = p["model"]
            rec["started"] = p["started"]
        recordings.append(rec)
    return jsonify(recordings)


@app.route("/api/recordings/<recording_id>", methods=["GET"])
@login_required
def get_recording(recording_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Recording not found"}), 404

    return jsonify({
        "id": row["id"],
        "original_filename": row["original_filename"],
        "display_name": row["display_name"],
        "file_size": row["file_size"],
        "duration_seconds": row["duration_seconds"],
        "transcript": row["transcript"],
        "status": row["status"],
        "created_at": row["created_at"],
        "transcribed_at": row["transcribed_at"],
    })


@app.route("/api/recordings/<recording_id>/rename", methods=["POST"])
@login_required
def rename_recording(recording_id):
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    conn = get_db()
    row = conn.execute("SELECT id FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Recording not found"}), 404
    conn.execute("UPDATE recordings SET display_name = ? WHERE id = ?", (name, recording_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "renamed", "display_name": name})


@app.route("/api/recordings/<recording_id>", methods=["DELETE"])
@login_required
def delete_recording(recording_id):
    conn = get_db()
    row = conn.execute("SELECT stored_filename FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Recording not found"}), 404

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], row["stored_filename"])
    if os.path.exists(file_path):
        os.remove(file_path)
    web_path = file_path.rsplit(".", 1)[0] + "_web.mp3"
    if os.path.exists(web_path):
        os.remove(web_path)

    conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


@app.route("/api/recordings/<recording_id>/retranscribe", methods=["POST"])
@login_required
def retranscribe(recording_id):
    conn = get_db()
    row = conn.execute("SELECT stored_filename, status FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Recording not found"}), 404
    if row["status"] == "transcribing":
        conn.close()
        return jsonify({"error": "Already transcribing"}), 409

    stored_path = os.path.join(app.config["UPLOAD_FOLDER"], row["stored_filename"])
    data = request.get_json(silent=True) or {}
    model_name = data.get("model", WHISPER_MODEL)
    if model_name not in [m["id"] for m in AVAILABLE_MODELS]:
        model_name = WHISPER_MODEL
    diarize = data.get("diarize", False)
    conn.execute("UPDATE recordings SET status = 'uploaded', transcript = NULL, model = ? WHERE id = ?", (model_name, recording_id))
    conn.commit()
    conn.close()

    transcription_queue.put((recording_id, stored_path, model_name, diarize))
    return jsonify({"id": recording_id, "status": "transcribing"})


@app.route("/api/retranscribe-all", methods=["POST"])
@login_required
def retranscribe_all():
    data = request.get_json(silent=True) or {}
    model_name = data.get("model", WHISPER_MODEL)
    if model_name not in [m["id"] for m in AVAILABLE_MODELS]:
        model_name = WHISPER_MODEL
    diarize = data.get("diarize", False)

    conn = get_db()
    rows = conn.execute(
        "SELECT id, stored_filename FROM recordings WHERE status != 'transcribing'"
    ).fetchall()
    conn.execute("UPDATE recordings SET status = 'uploaded', transcript = NULL, model = ? WHERE status != 'transcribing'", (model_name,))
    conn.commit()
    conn.close()

    for row in rows:
        stored_path = os.path.join(app.config["UPLOAD_FOLDER"], row["stored_filename"])
        transcription_queue.put((row["id"], stored_path, model_name, diarize))

    return jsonify({"queued": len(rows)})


@app.route("/api/recordings/batch/retranscribe", methods=["POST"])
@login_required
def batch_retranscribe():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"error": "No recordings specified"}), 400

    model_name = data.get("model", WHISPER_MODEL)
    if model_name not in [m["id"] for m in AVAILABLE_MODELS]:
        model_name = WHISPER_MODEL
    diarize = data.get("diarize", False)

    conn = get_db()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, stored_filename FROM recordings WHERE id IN ({placeholders}) AND status != 'transcribing'",
        ids,
    ).fetchall()
    conn.execute(
        f"UPDATE recordings SET status = 'uploaded', transcript = NULL, model = ? WHERE id IN ({placeholders}) AND status != 'transcribing'",
        [model_name] + ids,
    )
    conn.commit()
    conn.close()

    for row in rows:
        stored_path = os.path.join(app.config["UPLOAD_FOLDER"], row["stored_filename"])
        transcription_queue.put((row["id"], stored_path, model_name, diarize))

    return jsonify({"queued": len(rows)})


@app.route("/api/recordings/batch/delete", methods=["POST"])
@login_required
def batch_delete():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"error": "No recordings specified"}), 400

    conn = get_db()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, stored_filename FROM recordings WHERE id IN ({placeholders})",
        ids,
    ).fetchall()

    for row in rows:
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], row["stored_filename"])
        if os.path.exists(file_path):
            os.remove(file_path)
        web_path = file_path.rsplit(".", 1)[0] + "_web.mp3"
        if os.path.exists(web_path):
            os.remove(web_path)

    conn.execute(f"DELETE FROM recordings WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()
    return jsonify({"deleted": len(rows)})


@app.route("/api/recordings/<recording_id>/audio")
@login_required
def serve_audio(recording_id):
    conn = get_db()
    row = conn.execute("SELECT stored_filename FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Recording not found"}), 404

    original_path = os.path.join(app.config["UPLOAD_FOLDER"], row["stored_filename"])
    if not os.path.exists(original_path):
        return jsonify({"error": "File not found on disk"}), 404

    try:
        web_path = get_web_audio_path(original_path)
    except Exception as e:
        logger.error(f"Transcode error: {e}")
        return jsonify({"error": "Could not prepare audio for playback"}), 500

    return stream_file(web_path, "audio/mpeg")


@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory("static/js", "sw.js")


# Start background worker and requeue incomplete jobs on startup
start_worker()
requeue_incomplete(UPLOAD_FOLDER)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=1337, debug=False)
