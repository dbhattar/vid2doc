FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# deno: yt-dlp (routes/youtube.py) needs a JS runtime to solve YouTube's
# newer JS-based challenges (nsig/signature deciphering, PO token
# generation) -- without one, every "JS Challenge Provider" shows
# "(unavailable)" in yt-dlp's debug log and it falls back to client types
# (tv, visionos) that increasingly report LOGIN_REQUIRED outright, even with
# valid cookies. deno specifically, not nodejs: it's the only runtime
# yt-dlp auto-enables with zero extra flags (confirmed -- plain `apt install
# nodejs` plus `--js-runtimes node` still left node "(unavailable)" in
# testing; yt-dlp's own warning says "Only deno is enabled by default").
# Installed from a release binary (no official apt package) -- architecture-
# aware since this image is built on both arm64 (local/dev) and amd64
# (the production VPS). See youtube.py's _run_yt_dlp comment for the full
# cookie/client-selection history this is the latest chapter of, and
# https://github.com/yt-dlp/yt-dlp/wiki/EJS for yt-dlp's own docs on this.
RUN DENO_ARCH=$(dpkg --print-architecture | sed 's/amd64/x86_64-unknown-linux-gnu/;s/arm64/aarch64-unknown-linux-gnu/') \
    && curl -fsSL "https://github.com/denoland/deno/releases/latest/download/deno-${DENO_ARCH}.zip" -o /tmp/deno.zip \
    && unzip -o /tmp/deno.zip -d /usr/local/bin \
    && rm /tmp/deno.zip \
    && chmod +x /usr/local/bin/deno

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

# One shared image for both services -- docker-compose overrides `command`
# per service (api runs uvicorn, worker runs worker.py). The entrypoint runs
# pending Alembic migrations before either command starts, so both
# containers self-migrate on boot without a separate deploy step -- safe
# since `alembic upgrade head` is a no-op once the schema is current.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
