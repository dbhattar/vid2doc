# Integrating the dsh-cloud coding workspace into Framewrite

Status: **approved plan, not started** (2026-11-25). Nothing described here is built yet. The matching work in the dsh-cloud repo (`/Users/dipeshbhattarai/Projects/dsh-cloud`) is tracked there; this file is the vid2doc side of the plan and the shared picture.

## Context

**vid2doc** (Framewrite) turns video and audio into documents (Markdown, Word, PDF) and has an **Agents** menu: OpenAI-backed document-chat assistants (documents as a knowledge base, a catalog of tools and skills, memory; see `plan/agents-plan.md`). They have no shell or filesystem and are not coding agents. Stack: FastAPI + Postgres + worker (backend), Next.js 16 (frontend), one VPS with Docker Compose and nginx, Google sign-in, a session JWT kept in `localStorage` and sent as a header (no cookies).

**dsh-cloud** gives each signed-in user a sandboxed coding-agent workspace (DeepSeek Harness) behind its own gateway: own accounts, invite signup, token quotas, storage and run-time limits, gVisor sandboxes, audit log.

**Goal:** a **Workspace** item in vid2doc, next to Agents, where a vid2doc user gets a coding-agent workspace signed in automatically, can open a finished document in it (transcript, frames, Markdown), have the agent work on it (transform it, write code from a tutorial video, build something), and take results back.

**Decisions (2026-11-25):**
- **Depth:** embedded in vid2doc's page with single sign-on, built in stages (new-tab link first, then the embed).
- **Hosting:** dsh-cloud on a separate VM, own subdomain (for example `workspace.framewrite.cc`), so untrusted sandboxes stay away from vid2doc's database, Stripe keys and uploads.
- **Use case:** work on the user's documents, so import and export between the products matter.
- **Billing:** free beta behind a per-user flag (like `meetings_enabled`); dsh-cloud's token, storage and run-time limits cap cost. Wallet metering later.

## Shape of the integration

```
Browser on app.framewrite.cc (vid2doc, bearer token in localStorage)
   │ 1. POST /api/workspace/launch  (vid2doc API, needs the flag)  →  short-lived signed launch token
   │ 2. hidden form POST token →  workspace.framewrite.cc/gw/sso   (into an iframe, or a new tab in stage 1)
   ▼
dsh-cloud gateway: verifies the token, finds or creates the user, sets its own session cookie, serves the app (embed mode)

vid2doc backend ──service-to-service (HTTPS + secret)──▶ dsh-cloud: import files into a user's workspace / export results
```

Why a token handed over in a form POST: vid2doc authenticates by header, so an iframe cannot sign in by itself. The token never appears in a URL or log. The two sites share a registrable domain, so dsh-cloud's `SameSite=Lax` session cookie works inside the iframe.

**Token:** Ed25519-signed compact token (vid2doc holds the private key, dsh-cloud only the public key, verified with `node:crypto`, so the gateway keeps its no-dependencies rule). Claims: issuer, audience `dsh-cloud`, subject = vid2doc user id, email, name, `iat`, `exp` (about 60 s), single-use `jti`. dsh-cloud rejects a wrong algorithm, audience, expiry, replay and tampering.

**Identity:** dsh-cloud gets `external_issuer` and `external_id` on users (unusable password hash). A vid2doc user maps to exactly one workspace. vid2doc owns entitlement: its flag gates the launch; dsh-cloud's invite check does not apply to SSO users. SSO sessions are short (about 8 h) and the vid2doc page re-does the handshake on every visit, so turning the flag off takes effect within hours.

## Work in this repository (vid2doc)

Follow `AGENTS.md`: read the bundled Next.js docs before frontend work (`frontend/AGENTS.md`), develop through `./restart-containers.sh --dev`, and keep the sub-project READMEs authoritative.

- **Backend:**
  - `backend/app/routes/workspace.py`: `POST /api/workspace/launch` (session users only, like `get_current_session_user`; refuses without the flag), later `POST /api/workspace/open-job/{id}`.
  - Token signing with an Ed25519 private key from settings (`WORKSPACE_URL`, signing key; never committed, never logged).
  - A `workspace_enabled` flag and admin toggle next to `meetings_enabled`: `backend/app/feature_flags.py`, `User` column plus an Alembic migration, and `features.workspace` in `/api/auth/me`.
  - A milestone script `validation/milestone_workspace.py` in the repo's style (TestClient against Postgres): flag off refuses, flag on returns a verifiable token, claims and expiry, API keys cannot launch.
- **Frontend:**
  - A nav entry in `frontend/components/Sidebar.tsx` (`PRIMARY_NAV_LINKS`), shown only when `features.workspace` is true, like Meetings.
  - `frontend/app/(app)/workspace/page.tsx`: fetch the token with `apiFetch`, submit it by a hidden form POST into the iframe (or a new tab in stage 1), loading and error states.
  - Later: an **Open in workspace** action on the job page.
- **Leave the existing Agents feature unchanged** (`frontend/app/(app)/agents`, `backend/app/agents.py`, `agent_tools/`).
- **Docs:** `backend/README.md` (settings and routes), a short section in `frontend/README.md`, and an admin note for the flag.

## Work in dsh-cloud (for reference; tracked in that repo)

- `gateway/src/sso.js` (verify token, single-use `jti`), `POST /gw/sso`, config (`SSO_ENABLED`, `SSO_PUBLIC_KEY`, `SSO_ISSUER`, `SSO_AUDIENCE`, `SSO_SESSION_SECONDS`), users migration, audit events (`sso.login`, `sso.refused`), no open redirect through `next`.
- Embedding: `frame-ancestors` and `X-Frame-Options` configurable (today fixed to `'self'`), and an embed mode in the shell that hides brand, email and Sign out but keeps the usage panel.
- Real domain and TLS (`infra/Caddyfile.gateway` parametrised).
- Service API (`/svc/v1/...`, separate `SERVICE_SECRET`, unreachable from sandboxes) for import and export; runner support for writing into a user's workspace volume.
- `docs/vid2doc-integration.md` (the contract), tests, and `scripts/linux/setup-host.sh` to provision the separate Linux VM (Docker, gVisor, firewall).

## Stages

0. **Prerequisites** (both repos): domain and VM, signing keys, flag name. Spike (small): a test parent page on one subdomain embedding the gateway on another, driven by Playwright, to verify what is unproven: the nested harness frame is allowed when embedded (CSP `frame-ancestors` is checked against the whole ancestor chain, and the harness's own headers have not been looked at), the session cookie works in the iframe, clipboard and fullscreen pass through.
1. **SSO and a new-tab link** (medium): flag, launch route, `POST /gw/sso`, users migration, Workspace menu item opening the workspace in a new tab. Demo: a flagged user clicks Workspace and lands in a running workspace, signed in.
2. **Embed** (medium): frame headers, embed mode, the iframe page here, sign-out and expiry behaviour, limit and error states (dsh-cloud already renders designed states inside the frame).
3. **Open a document in the workspace** (medium to large): vid2doc builds a bundle (`document.md`, transcript, frames zip, a small metadata file) and sends it to dsh-cloud's import API, which writes it under `/workspace/deepseek-harness/default-workspace/vid2doc/<title>/` owned by the agent's user. The runner rejects absolute paths, `..`, links and special files, with size caps. **To verify:** whether Docker's archive upload works for a volume of a container with a read-only root; otherwise a short-lived helper container with the volume is used.
4. **Results back** (medium to large): export API (list and download chosen paths as an archive); a "Save to my documents" action here that stores the result (derived documents, Drive export or a new artifact type; needs its own small design); a delete-my-data call so removing a user here removes their workspace.
5. **Later:** wallet metering (dsh-cloud reports tokens and workspace hours, vid2doc debits the Stripe-backed wallet), existing Agents calling a workspace as a tool (needs a way to message a workspace without a browser, not yet proven), one admin view.

## Security and operations notes

- A compromise of a sandbox must not reach vid2doc: separate VM, no shared network, the service secret and public key only on the dsh-cloud side, service endpoints not exposed to sandbox networks, rate limits and audit on every service call. **The signing key stays in vid2doc.**
- Launch tokens: short expiry, single use, audience-bound, algorithm pinned. An XSS in vid2doc can launch the same user's workspace but not anyone else's.
- Privacy: the user's documents are copied to the workspace host. Say so in the UI, honour deletion, keep document content out of logs and audit.
- Two codebases, one contract: the contract lives in dsh-cloud's `docs/vid2doc-integration.md` and each side has a contract test (a token minted by this repo's code verifies in dsh-cloud's, and each failure case is refused).
- vid2doc's current production setup has no CSP or `frame-ancestors`; nothing here requires adding one, but if one is added later it must allow the workspace origin in `frame-src`.

## Verification

- Unit and milestone checks as described above, plus dsh-cloud's token verification matrix (valid; expired; wrong audience, issuer or algorithm; tampered; replayed `jti`; unknown key).
- Live: dsh-cloud's Docker suites stay green under gVisor; a new suite there for SSO and import. A browser test (Playwright) with a parent page on a sibling subdomain: the user arrives signed in, the usage panel works, Stop and Restart work inside the frame.
- Cross-repo end to end in dev: two local hostnames with the same registrable domain (hosts file plus Caddy internal TLS), vid2doc via `./restart-containers.sh --dev`, dsh-cloud in its Lima VM; walk the stages: launch, embed, open a real finished job in the workspace, make the agent edit it, export back.
- Each stage ends with a real-browser look.

## Open questions

- Domain and subdomain names, and who provisions the VM and DNS.
- How the entitlement flag is managed: admin toggle only, or also request-access.
- Where exported results should live in vid2doc (derived documents, Drive, or a new artifact type).
- Whether a user may have more than one workspace (the plan assumes one).
- Quota defaults for the free beta (tokens per day, storage, run time).

## Process

One task per pull request in each repo, on topic branches, with tests, documentation and scripts for repeatable steps, following each repo's `AGENTS.md`. The first tasks are stage 0's embedding spike and the contract document in dsh-cloud.
