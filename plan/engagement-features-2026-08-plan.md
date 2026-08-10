# Framewrite — engagement features + repo docs

## Context
User asked for suggestions to make the whole product (marketing + app + backend) more engaging/useful, spanning conversion, sign-up, trust, UX polish, and new features. After surveying `backend/`, `frontend/`, and `marketing/` directly, a 20-item menu was produced and the user picked 4 for implementation now: **job-completion email**, **in-app document preview**, **shareable public doc link**, and a **marketing trust pass** (testimonials, FAQ, newsletter capture). The user also separately asked for root-level `AGENTS.md`/`CLAUDE.md`, with an explicit instruction that approved plan files get saved into the repo's existing `plan/` folder going forward.

Note: while planning, `frontend/AGENTS.md`'s "This is NOT the Next.js you know... read node_modules/next/dist/docs/" content was checked — it's real (Next 16.2.10 ships that docs folder) and was committed by the user themselves (`git log`: "Milestone 2: Add auth"), not an injected/planted instruction. No action needed, just flagging that it was verified.

---

## 1. Backend — job-completion email

`Job.status` only ever flips to `"done"`/`"failed"` at two chokepoints in `backend/app/pipeline.py`: `_finalize_document()` (covers every "done" path, including human-in-the-loop review resume) and `run_job()`'s outer `except Exception` (covers every failure path). A third, optional site is `backend/retention.py`'s stale-review sweep.

**Changes:**
- `backend/app/emails.py` — add `send_job_done_email(user, job)`, `send_job_failed_email(user, job)` (same brand-constant/`html.escape` style as the existing `send_welcome_email`), and a dispatcher:
  ```python
  def notify_job_status_change(job_id: str) -> None:
      # re-fetches the job fresh; skips if user_id is None (trial/anon) or
      # status not in ("done","failed"); wraps everything in try/except so
      # a mail failure can never affect the job's own status.
  ```
- `backend/app/pipeline.py` — call `emails.notify_job_status_change(job_id)` right after the `status="done"` update in `_finalize_document`, and right after the `status="failed"` update in `run_job`'s except block (after the refund check).
- `backend/retention.py` (optional) — same call after its `awaiting_review` → `failed` sweep update.
- No DB migration needed — no schema change.
- Link in the email points to `{settings.FRONTEND_URL}/dashboard/jobs/{job_id}` (route already exists).

**Verify:** run a job end-to-end with no Mailgun creds set → confirm "not configured, skipping" log and job still reaches done/failed normally. Force a failure → confirm same no-op path + refund still happens. Create a trial (`user_id=None`) job → confirm no email lookup happens at all. With real `MAILGUN_API_KEY`/`MAILGUN_DOMAIN` set, confirm the email actually arrives with a working link.

---

## 2. Backend — shareable public document link

New nullable `jobs.share_token` column (`share_token IS NULL` = not shared, same convention as `user_id IS NULL` meaning trial). Stored **in plaintext** (unlike hashed API keys) since the owner must be able to see/copy the same link repeatedly.

**Changes:**
- `backend/app/models.py` — add `share_token: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)` to `Job`.
- `backend/alembic/versions/0011_job_share_token.py` — new migration, `down_revision="0010"`, adds the column + unique index.
- `backend/app/jobs.py` — add `share_token` to `_job_to_dict`; add `get_job_by_share_token(token)`.
- `backend/app/routes/share.py` (new) — modeled on `routes/trial.py`'s tokenless-access pattern:
  - `POST /api/jobs/{job_id}/share` (owner-only, idempotent — returns existing token if already shared, requires `status=="done"` and not retention-expired) → `{share_token, share_url}`.
  - `DELETE /api/jobs/{job_id}/share` (owner-only) → 204, clears the token.
  - `GET /api/share/{token}` → public job info (title, job_type, duration_seconds, created_at, document URLs) — never includes `user_id`/`client_ip`/`billed_cents`/`error_message`.
  - `GET /api/share/{token}/documents/bundle.zip` and `GET /api/share/{token}/documents/{file_path:path}` — public file serving, path-confined via `is_relative_to(doc_dir)` (same guard `routes/documents.py` uses). Bundle route registered *before* the catch-all (Starlette ordering, same as `routes/trial.py`).
- `backend/app/main.py` — register `share.router`.
- `backend/app/routes/status.py` — add `share_url` to the **owner's own** `build_job_response` so the dashboard can show current share state without an extra round-trip.

**Verify:** migrate, then exercise via a `validation/`-style script: owner enables share (idempotent on 2nd call), a different user gets 404 trying to enable it, public `GET /api/share/{token}` works with no auth header and leaks none of the excluded fields, bundle.zip/document.md download with no auth, disable revokes immediately (old token → 404), and a job that becomes `failed`/retention-expired after being shared 404s on the stale token.

---

## 3. Frontend — in-app document preview + share UI

Documents are served from the app's own FastAPI file server (not S3/GCS), behind Bearer auth for the owner path — so rendering requires authenticated fetches, not plain `<img src>`. `AuthenticatedImage` and `downloadAuthenticated` (in `frontend/lib/api.ts`) already do this blob-fetch-with-conditional-header dance and get reused as-is.

**New/changed files:**
- `frontend/package.json` — add `react-markdown` + `remark-gfm` (no markdown renderer exists yet; GFM needed for the pipe tables `assemble.py` emits).
- `frontend/lib/api.ts` — add `fetchAuthenticatedText(url)`, same shape as `downloadAuthenticated` but returns text.
- `frontend/components/DocumentPreview.tsx` (new) — fetches the raw markdown, renders via `react-markdown`+`remark-gfm` with `components` overrides matching the app's existing sharp-cornered/mono-uppercase design tokens (`--ink`/`--paper`/`--paper-shade`/`--line`/`--accent`). Images resolved via relative-URL math against `markdownUrl` and rendered through the existing `AuthenticatedImage`. Built so it works unmodified on both the owner's job page and the public share page (no `authenticated` prop needed).
- `frontend/app/(app)/dashboard/jobs/[id]/page.tsx` — render `<DocumentPreview markdownUrl={job.document_url} />` inside the existing `status==="done" && !retention_expired` block, alongside (not replacing) `TranscriptViewer` for audio jobs.
- `frontend/lib/jobs.ts` — extend `Job` with `share_token?`/`share_url?` (matches backend's `status.py` addition); add a `PublicJobView` type for the public endpoint's shape.
- `components/icons.tsx` — add a `ShareIcon` wrapping `lucide-react`'s `Share2`, following the existing icon-wrapper convention.
- `frontend/components/ShareControl.tsx` (new, owner-only) — "Share" button → `POST /api/jobs/{id}/share`, shows the URL in a copy-to-clipboard box (same pattern as the API-keys page's reveal box) + a "Disable sharing" action → `DELETE`. Rendered on the job detail page next to the download buttons, gated on the same `done && !retention_expired` condition.
- `frontend/app/share/[token]/page.tsx` (new, public — lives outside the `(app)` route group so it gets no Sidebar/TopBar/auth redirect) — fetches `GET /api/share/{token}`, shows title/minimal metadata, download buttons, and the reused `DocumentPreview`. Explicitly omits `TranscriptViewer` (hits an owner-only endpoint) and any billing/Retry/Delete/Drive actions. 404 state shows "This link is invalid or sharing has been turned off" — never redirects to `/login`.

**Verify:** `npm run dev` against the running backend. On a finished job, click Share, copy the link, open it in an incognito window — confirm it renders with no Sidebar/billing/auth chrome and no `Authorization` header on the network requests. Confirm images and tables render correctly in both light and dark mode (toggle via the dashboard's `ThemeToggle`, dark-mode state persists across routes via `localStorage`). Disable sharing on the owner side and confirm the previously-copied link now 404s. Repeat the preview check on a job that's still processing/failed to confirm it doesn't render at all.

---

## 4. Marketing — testimonials, FAQ, newsletter capture

New homepage order: `Hero → TrialUpload → Testimonials(new) → WhatsNewGrid → FeatureGrid → PricingTable → FAQ(new) → EnterpriseCta → FinalCta → Newsletter(new)`. All new sections are plain `.astro` (no React/Vue in this project), styled only with `var(--token)` values from `tokens.css` so light/dark mode "just works."

**FAQ** — `marketing/src/components/FAQ.astro`, native `<details>/<summary>` accordion (no JS). Content is grounded strictly in existing copy/config, not invented: pricing ($1/hr video, $0.40/hr audio, from `PricingTable.astro`/README), trial limits (10min video/30min audio/2 tries per day/Turnstile, from `TrialUpload.astro` + `backend/app/config.py`), retention (trial ~6hrs hard-deleted vs. account 7-day retention — must match `privacy.astro` exactly, these numbers differ and shouldn't be conflated), supported file types + YouTube import, and a vendor-neutral accuracy answer (no naming AssemblyAI/Whisper/Anthropic publicly). Wire into `index.astro` between `PricingTable` and `EnterpriseCta`; optionally add a `/#faq` link to `Header.astro`'s nav.

**Newsletter capture** — recommended approach: **Mailgun mailing list** via a new minimal public backend endpoint (not a 3rd-party embed, not a new DB table) — `backend/app/mailgun_client.py` already has a working Mailgun client, so this is the smallest addition with no new vendor.
- `backend/app/config.py` — add `MAILGUN_NEWSLETTER_LIST` setting (list itself created once via Mailgun dashboard).
- `backend/app/mailgun_client.py` — add `add_to_mailing_list(email)`, best-effort/no-op-if-unconfigured like `send_email`.
- `backend/app/routes/newsletter.py` (new) — `POST /api/public/newsletter`, regex email validation (no `EmailStr` dependency needed), no Turnstile (low abuse value; double opt-in is a Mailgun list-level setting instead).
- `backend/app/main.py` — register the router.
- `marketing/src/components/Newsletter/Newsletter.astro` + `newsletter.ts` (new, mirrors `FeedbackWidget`'s structure) — quiet band (not the bold `FinalCta` treatment), placed after `FinalCta` as the last homepage section.

**Testimonials** — `marketing/src/data/testimonials.ts` (plain array, not a content collection) with 2-3 **clearly-marked placeholder** entries (`placeholder: true` flag, obvious "replace before shipping" text) — real quotes don't exist yet and must come from the user later; do not fabricate realistic-looking fake names/companies. `marketing/src/components/Testimonials.astro` renders a 3-column card grid (collapsing to 1 column under 640px, matching `PricingTable`'s breakpoint) with a small "Sample" tag on placeholder cards (reusing the existing "New" pill visual language from `WhatsNewGrid.astro`). Wire into `index.astro` right after `TrialUpload`.

**Verify:** `npm run dev`, check all three sections render correctly in light/dark (via the header's `ThemeToggle`) and at the 900px/780px/640px breakpoints already used elsewhere on the page. Submit the newsletter form with the backend running and confirm a 202 + success state (works even without real Mailgun creds — logs "not configured, skipping"); submit an invalid email and confirm the 400 path. `npm run build && npm run preview` before treating this as done, to catch build-time errors.

---

## 5. Repo docs — root `AGENTS.md` + `CLAUDE.md`

Repo has no root-level `AGENTS.md`/`CLAUDE.md` today (only `frontend/` and `marketing/` have them). Follow the existing convention: `AGENTS.md` holds real content, `CLAUDE.md` is just `@AGENTS.md` (the import form `frontend/CLAUDE.md` already uses, cleaner than `marketing/CLAUDE.md`'s duplication since it can't drift).

**Root `AGENTS.md` content:**
1. **Plan-file instruction (explicit user ask):** once a Claude Code plan is approved in this repo, save/copy the approved plan file into the root `plan/` folder (not left only in `~/.claude/plans/`), following the existing naming convention already used there: `<topic>-plan.md`, kebab-case.
2. Repo orientation — pointer to root `README.md` as the authoritative map, not a duplicate of it.
3. Sub-project docs (`backend/README.md`, `frontend/README.md`, `marketing/README.md` + their own `AGENTS.md`/`CLAUDE.md`) are authoritative for how to work inside each — don't re-derive conventions.
4. Local dev entry points: `./restart-containers.sh --dev` from repo root for backend+frontend; `cd marketing && npm run dev` (or `astro dev --background`) for marketing — run independently, never together.
5. `plan/` is historical design-intent, not living docs — code and READMEs are authoritative for current behavior.

**Root `CLAUDE.md`:** single line, `@AGENTS.md`.

---

## Execution order
Backend pieces (#1, #2) have no UI dependency and can go first. Frontend (#3) depends on the share-link API contract from #2 (already cross-checked — matches). Marketing (#4) and repo docs (#5) are fully independent of the others and can happen in any order, including in parallel with the backend/frontend work.

## Verification summary
Each section above has its own verification steps (run the dev servers, exercise the new endpoints/UI, check light+dark mode, confirm no data leaks on the public share path). After implementation, save this plan file into `plan/` per the new root `AGENTS.md` convention being added in step 5 — e.g. as `plan/engagement-features-2026-08-plan.md`.
