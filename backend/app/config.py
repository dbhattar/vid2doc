import os
from pathlib import Path


class Settings:
    # Verifies the ID token the frontend gets from Google Identity Services.
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    # OAuth2 web client secret -- needed for the server-side auth-code
    # exchange used by the Google Drive integration (see routes/drive.py).
    # GOOGLE_CLIENT_ID above is reused for both Sign-In-with-Google ID token
    # verification AND this flow, since it's the same Google Cloud OAuth
    # client -- just needs Drive API enabled + drive.file scope allowed on
    # that client's OAuth consent screen.
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    # Signs the app-issued session JWT handed back after Google verification.
    JWT_SECRET = os.environ.get("JWT_SECRET", "dev-jwt-secret-change-me")
    JWT_EXPIRES_DAYS = int(os.environ.get("JWT_EXPIRES_DAYS", 7))

    # Symmetric key for encrypting stored Google Drive OAuth refresh tokens
    # (Fernet, base64-encoded 32-byte key -- generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    # Frontend origin(s) allowed to call this API from the browser (comma-separated).
    # Must be exact scheme+host+port -- no wildcards, no trailing slash.
    CORS_ALLOWED_ORIGINS = [
        o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()
    ]

    # Emails (comma-separated, case-insensitive) auto-granted admin on every
    # login (see users.get_or_create_user_by_google) -- a durable allowlist,
    # not a one-time bootstrap: removing an email here doesn't demote anyone
    # already admin, it just stops future auto-grants for it. Anyone else
    # becomes admin only via the admin dashboard's toggle.
    ADMIN_EMAILS = {
        e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
    }

    # Stripe: wallet top-up checkout + webhooks (see app/stripe_client.py, app/billing.py).
    # No fixed Price ids -- top-up amount is user-chosen, passed as Checkout
    # line_item price_data at request time (see routes/billing.py).
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    # Where Stripe Checkout redirects back to after a session.
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    # Kill switch for new top-ups (e.g. a Stripe-side incident) -- existing
    # wallet balances and job processing are unaffected either way, this only
    # gates POST /api/billing/checkout/topup. Set to "false" to disable.
    PAYMENTS_ENABLED = os.environ.get("PAYMENTS_ENABLED", "true").strip().lower() != "false"

    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://vid2doc:vid2doc@postgres:5432/vid2doc"
    )

    DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
    UPLOADS_DIR = DATA_DIR / "uploads"
    OUTPUT_DIR = DATA_DIR / "output"

    MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024))  # 2GB
    MAX_DURATION_SECONDS = int(os.environ.get("MAX_DURATION_SECONDS", 90 * 60))  # 90 min
    ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    # Audio-only transcript jobs (POST /api/transcribe_audio) -- verbatim,
    # speaker-tagged transcript, no frame capture/document composition.
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}

    # auto: assemblyai if ASSEMBLYAI_API_KEY set, else baseten if BASETEN_API_KEY
    # set, else the job fails with a clear config error (see
    # pipeline.py's _resolve_engine() -- no local-CPU fallback anymore).
    TRANSCRIPTION_ENGINE = os.environ.get("TRANSCRIPTION_ENGINE", "auto")
    # Passed through to Baseten's remote model, not used locally.
    WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")

    # LLM provider for the vision-judgment and topic-segmentation stages.
    # anthropic (default): claude-sonnet-5. openai: gpt-5.4-mini (vision + structured outputs, cost-efficient).
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")

    WORKER_POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", 2.0))

    # Mailgun: transactional email (e.g. the first-login welcome email, see
    # app/mailgun_client.py). No-op if MAILGUN_API_KEY/MAILGUN_DOMAIN are unset,
    # so local dev/CI never need real credentials.
    MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
    MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
    MAILGUN_FROM_EMAIL = os.environ.get("MAILGUN_FROM_EMAIL", "Framewrite <noreply@framewrite.cc>")
    # EU-region Mailgun accounts use https://api.eu.mailgun.net/v3 instead.
    MAILGUN_BASE_URL = os.environ.get("MAILGUN_BASE_URL", "https://api.mailgun.net/v3")
    # Mailgun's own test mode (o:testmode=yes): validates the API key/domain and
    # request shape, logs the call in the Mailgun dashboard, but never actually
    # delivers the email. Lets you verify the whole integration against a real
    # Mailgun account locally without risking a real send. Leave false in prod.
    MAILGUN_TEST_MODE = os.environ.get("MAILGUN_TEST_MODE", "false").strip().lower() == "true"
    # Debug-only: sends the welcome email on every login, not just the first,
    # so you can iterate on copy/design without creating a fresh account each
    # time. Never enable in production.
    ALWAYS_SEND_WELCOME_EMAIL = os.environ.get("ALWAYS_SEND_WELCOME_EMAIL", "false").strip().lower() == "true"
    # Mailgun mailing list (created once via the Mailgun dashboard, e.g.
    # news@mg.framewrite.cc) the homepage newsletter signup adds addresses to
    # (see mailgun_client.add_to_mailing_list). No-op (skipped, not an error)
    # if unset, same as MAILGUN_API_KEY/DOMAIN above.
    MAILGUN_NEWSLETTER_LIST = os.environ.get("MAILGUN_NEWSLETTER_LIST", "")

    # Anonymous "try it free" upload on the marketing site (routes/trial.py) --
    # no wallet/billing gate, so these caps plus Turnstile are what stand in
    # for it. Deliberately much tighter than the authenticated caps above.
    TRIAL_MAX_VIDEO_DURATION_SECONDS = int(os.environ.get("TRIAL_MAX_VIDEO_DURATION_SECONDS", 10 * 60))
    TRIAL_MAX_AUDIO_DURATION_SECONDS = int(os.environ.get("TRIAL_MAX_AUDIO_DURATION_SECONDS", 30 * 60))
    TRIAL_MAX_UPLOAD_BYTES = int(os.environ.get("TRIAL_MAX_UPLOAD_BYTES", 300 * 1024 * 1024))  # 300MB
    TRIAL_MAX_PER_IP_PER_DAY = int(os.environ.get("TRIAL_MAX_PER_IP_PER_DAY", 2))
    TRIAL_RETENTION_HOURS = int(os.environ.get("TRIAL_RETENTION_HOURS", 6))
    # Cloudflare Turnstile secret key (see app/turnstile.py) -- verify_turnstile_token
    # fails closed if this is unset, so trial uploads are simply rejected
    # rather than silently unprotected in an environment that forgot to set it.
    TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

    # Audio -> generated video (routes/video_gen.py, job_type == "video_gen").
    # Pexels: free API, both photo and video search, permissive commercial
    # license (see stages/stock_media.py). No SDK -- plain requests calls.
    PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
    STOCK_MEDIA_PROVIDER = os.environ.get("STOCK_MEDIA_PROVIDER", "pexels")
    # Stricter than MAX_DURATION_SECONDS above -- ffmpeg rendering is far more
    # CPU/wall-clock-heavy than the mostly I/O-bound video/audio pipelines,
    # and worker.py has no concurrency, so one long video_gen job would tie
    # up every other queued job behind it.
    VIDEO_GEN_MAX_DURATION_SECONDS = int(os.environ.get("VIDEO_GEN_MAX_DURATION_SECONDS", 20 * 60))


settings = Settings()
