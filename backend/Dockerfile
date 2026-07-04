FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# --extra-index-url makes CPU-only torch wheels available to the resolver
# alongside PyPI, so it can satisfy torch (needed by openai-whisper and
# pyannote.audio) without falling back to PyPI's default CUDA-bundled build --
# multiple GB smaller, and no NVIDIA drivers needed on a VPS.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY . .

# One shared image for both services -- docker-compose overrides `command`
# per service (api runs uvicorn, worker runs worker.py).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
