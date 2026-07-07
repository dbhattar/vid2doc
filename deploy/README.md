# Deployment (Fabric)

Deploys the whole stack (Postgres, API, worker, frontend, all via
`backend/docker-compose.yml`) to a single Ubuntu/Debian VPS, with nginx as
the reverse proxy and Let's Encrypt for TLS. Two domains:
`app.framewrite.cc` (frontend) and `api.framewrite.cc` (backend API).

See `fabfile.py`'s module docstring for the exact command sequence
(bootstrap → fill `.env` by hand → point DNS → `setup-tls` → `deploy`). This
file covers the *why*; that one covers the *how to run it*.

## Setup

```bash
cd deploy
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Before you run anything

Edit the constants at the top of `fabfile.py`:

- `APP_DIR` — where the repo lives on the VPS (default `/opt/framewrite`)
- `GIT_REPO_URL` — defaults to this repo's own SSH remote, which means the
  VPS needs its own deploy key (steps are in a comment right above
  `NGINX_CONF` in `fabfile.py`). Switch to the HTTPS clone URL instead if
  the repo is public and you'd rather skip that.
- `CERTBOT_EMAIL` — real email for Let's Encrypt expiry/renewal notices

## Why `.env` is never scripted

No task here creates or edits `backend/.env` — it holds production secrets
(Stripe live key, JWT secret, Postgres password) that shouldn't be baked
into a script that might get committed, logged, or shared. `bootstrap`
prints a reminder to create it by hand; `deploy` refuses to run at all if
it's missing, specifically to prevent ever accidentally starting production
with the insecure dev defaults from `.env.example`.

## Why `git reset --hard` is safe here

`deploy` runs `git fetch` + `git reset --hard origin/main` on the VPS to
pick up the latest commit. This only touches *tracked* files. `backend/.env`
and `backend/data/` (Postgres's data dir, uploads, generated documents) are
both gitignored — untracked — so a hard reset can never touch either of
them, no matter what.

## Tasks

| Task | What it does |
|---|---|
| `bootstrap` | One-time: installs Docker/nginx/certbot, clones the repo, writes the (HTTP-only) nginx config. Idempotent — re-running it skips anything already done. |
| `setup-tls` | Provisions Let's Encrypt certs for both domains via certbot's nginx plugin (also patches nginx to add HTTPS + redirect). Run once DNS for both domains resolves to the server. |
| `deploy` | Pulls the latest commit, rebuilds changed images, restarts the stack. This is what you run for every subsequent deploy. |
| `restart` | Restarts without rebuilding — e.g. after hand-editing `.env` (env vars are only re-read on container start). |
| `logs` | Tails one service's logs: `fab ... logs --service=worker --lines=200`. |

## Notes

- Every privileged step uses `c.sudo(...)`. Passwordless sudo for the SSH
  user is simplest; otherwise pass `--prompt-for-sudo-password` to `fab`.
- Migrations run automatically — `docker-entrypoint.sh` (inside the image)
  runs `alembic upgrade head` before the `api`/`worker` processes start, so
  `deploy` never needs a separate migration step.
- The nginx config sets `client_max_body_size 2100M` and disables request
  buffering on the API domain specifically — without it, nginx would reject
  large video uploads with a 413 before FastAPI ever saw them.
