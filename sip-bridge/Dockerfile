FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt edge-tts

# Copy application code
COPY *.py ./

VOLUME ["/sounds"]

EXPOSE 5001 9091

CMD ["python", "bridge.py"]