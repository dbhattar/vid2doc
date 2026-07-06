import os
from pathlib import Path


class Settings:
    API_KEY = os.environ.get("API_KEY", "dev-secret-key")

    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://vid2doc:vid2doc@postgres:5432/vid2doc"
    )

    DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
    UPLOADS_DIR = DATA_DIR / "uploads"
    OUTPUT_DIR = DATA_DIR / "output"

    MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024))  # 2GB
    MAX_DURATION_SECONDS = int(os.environ.get("MAX_DURATION_SECONDS", 90 * 60))  # 90 min
    ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

    # auto: assemblyai if ASSEMBLYAI_API_KEY set, else whisper-diarized if HF_TOKEN set, else whisper
    TRANSCRIPTION_ENGINE = os.environ.get("TRANSCRIPTION_ENGINE", "auto")
    WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")

    # LLM provider for the vision-judgment and topic-segmentation stages.
    # anthropic (default): claude-sonnet-5. openai: gpt-5.4-mini (vision + structured outputs, cost-efficient).
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")

    WORKER_POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", 2.0))


settings = Settings()
