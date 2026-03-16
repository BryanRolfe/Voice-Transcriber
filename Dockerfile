FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only PyTorch first (much smaller than GPU version)
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the default faster-whisper model
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('medium.en', device='cpu', compute_type='int8')"

COPY . .

RUN mkdir -p /data/uploads

EXPOSE 1337

CMD ["sh", "-c", "python -c 'from db import init_db; init_db()' && gunicorn --bind 0.0.0.0:1337 --workers 1 --timeout 600 app:app"]
