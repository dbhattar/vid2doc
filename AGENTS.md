# Framewrite — agent instructions

## Repo orientation
This repo contains the whole product, not just one piece of it. `README.md`
is the authoritative map of the top-level layout (`marketing/`, `backend/`,
`frontend/`, `validation/`, `deploy/`, `local_test/`, `plan/`) — read it
before assuming a directory's purpose.

## Sub-project docs are authoritative
`backend/README.md`, `frontend/README.md`, and `marketing/README.md` (and
their own `AGENTS.md`/`CLAUDE.md`) are the source of truth for conventions,
dev commands, and architecture inside each sub-project. Don't re-derive
conventions from scratch when working inside one — read the local docs
first.

## Local dev entry points
- Backend + frontend: `./restart-containers.sh --dev` from the repo root
  (Docker Compose). Must be run from the root — it resolves `backend/`
  relative to its own location.
- Marketing site: `cd marketing && npm run dev` (or `astro dev --background`
  per `marketing/AGENTS.md`).

These run independently — the marketing site is a separate Astro project,
never started together with the backend/frontend stack.

## Plan files
Once a Claude Code plan in this repo is approved, save the approved plan
file into the root `plan/` folder (not left only in the default
`~/.claude/plans/` location), following the naming convention already used
by every file already in `plan/`: `<topic>-plan.md`, kebab-case, descriptive.

`plan/` itself is a historical record of design intent from before each
piece was built, not living documentation — the code and the READMEs above
are authoritative for current behavior.
