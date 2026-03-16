import os
import subprocess
from flask import request, Response


def get_web_audio_path(original_path):
    """Return path to a browser-compatible MP3 version, transcoding if needed."""
    base = original_path.rsplit(".", 1)[0]
    web_path = base + "_web.mp3"
    if not os.path.exists(web_path):
        cmd = [
            "ffmpeg", "-y", "-i", original_path,
            "-ar", "44100", "-ac", "2", "-b:a", "128k",
            web_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg transcode failed: {result.stderr.decode()}")
    return web_path


def stream_file(file_path, mime_type):
    """Stream a file with range request support."""
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("Range")

    if not range_header:
        def generate_full():
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk
        return Response(generate_full(), status=200, headers={
            "Content-Type": mime_type,
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        })

    try:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
    except (ValueError, IndexError):
        return Response("Invalid Range", status=416)

    end = min(end, file_size - 1)
    if start > end or start < 0:
        return Response("Range Not Satisfiable", status=416,
                        headers={"Content-Range": f"bytes */{file_size}"})

    length = end - start + 1

    def generate_range():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return Response(generate_range(), status=206, headers={
        "Content-Type": mime_type,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
    })
