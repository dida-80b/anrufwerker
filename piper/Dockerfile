FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# piper-tts wird ohne onnxruntime-Dep installiert,
# dann versuchen wir onnxruntime-rocm für AMD GPU (gfx1100 / RX 7900 XT).
# Fallback auf CPU onnxruntime wenn ROCm-Paket nicht verfügbar ist.
RUN pip install --no-cache-dir piper-phonemize || true
RUN pip install --no-cache-dir piper-tts --no-deps
RUN pip install --no-cache-dir \
        onnxruntime-rocm \
        --index-url https://repo.radeon.com/rocm/manylinux/rocm-rel-6.2/ \
    || pip install --no-cache-dir onnxruntime
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" aiofiles pydantic

COPY server.py .

# ROCm: override GFX version für gfx1100 (RX 7900 XT) mit älterem ROCm-Treiber
ENV HSA_OVERRIDE_GFX_VERSION=11.0.0
ENV VOICES_DIR=/voices
ENV PORT=5150

VOLUME ["/voices"]
EXPOSE 5150

CMD ["python3", "server.py"]
