FROM python:3.11-slim

# Install ffmpeg (needed for Whisper STT)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create needed directories
RUN mkdir -p uploads static

# Expose port (Render sets $PORT)
EXPOSE 10000

# Start with gunicorn + uvicorn workers
CMD gunicorn app:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-10000} --timeout 120
