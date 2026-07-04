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
# multiple GB smaller, and no NVIDIA drivers needed since most cloud deploy
# targets have no GPU anyway.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY . .

# No fixed pipeline entrypoint -- run_pipeline.py and the numbered stage
# scripts are each invoked directly, e.g.:
#   docker run --rm -v $(pwd)/data:/data --env-file .env vid2doc-pipeline \
#     run_pipeline.py /data/video.mp4 --output-dir /data/output
ENTRYPOINT ["python3"]
CMD ["run_pipeline.py", "--help"]
