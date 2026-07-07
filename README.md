# Framewrite

Turn any video into a searchable document — automatic transcription, speaker
diarization, relevant frame capture, and clean document formatting, exported
to Markdown, Word, and PDF. Pay-as-you-go: $1.00 per hour of video, no
subscription.

Live marketing site: [framewrite.cc](https://framewrite.cc).

## Repo layout

This repo contains the whole product, not just one piece of it:

- **`index.html` / `styles.css` / `script.js` / `thanks.html`** — the static
  marketing site (hero, pricing, waitlist-style signup form), deployed to
  Netlify directly from this repo. Framework-free by design.
- **`backend/`** — the actual product: a FastAPI API + worker service
  (Google OAuth, per-user API keys, the video→document pipeline, Stripe
  wallet billing, retention). See `backend/README.md` — that's the real
  source of truth for how the product works.
- **`frontend/`** — the signed-in Next.js app (login, submit conversions,
  track jobs, download documents, manage API keys, manage billing). See
  `frontend/README.md`. Dockerized alongside the backend, not deployed
  separately.
- **`validation/`** — linear scripts that exercise real HTTP flows against
  the backend (auth, API keys, jobs, billing, retention) without needing a
  live Stripe/Google account for most of it. See `validation/README.md`.
- **`restart-containers.sh`** — dev helper: frees up host ports, rebuilds,
  and restarts the full Docker stack. Pass `--dev` to also start the Stripe
  CLI webhook listener.
- **`local_test/`** — standalone prototype scripts that validated each
  pipeline stage (transcription, frame extraction, vision classification,
  composition) against a real video before any of it was wired into
  `backend/`. Historical — `backend/app/stages/` is the real implementation
  now; this remains as a reference for experimenting with the pipeline
  stages in isolation.
- **`plan/`** — planning docs from before each major piece was built.
  Historical record of design intent, not living documentation — the code
  and the READMEs above are authoritative for current behavior.

## Local development

The product (backend + frontend) runs via Docker Compose from `backend/`:

```bash
cd backend && cp .env.example .env && cd ..   # fill in real values -- see backend/README.md
./restart-containers.sh --dev
```

(`restart-containers.sh` must be run from the repo root — it resolves
`backend/` relative to its own location.)

The marketing site has no build step — just serve the directory root:

```bash
python3 -m http.server 8080
```

## Deployment

- Marketing site → Netlify, directly from this repo's root (`netlify.toml`).
- Product (backend + frontend) → a single VPS via Docker Compose. See
  `backend/README.md`'s "Deploying to a VPS" section for the full checklist
  (Postgres, Google OAuth origins, Stripe webhook registration, TLS/reverse
  proxy, etc.).
