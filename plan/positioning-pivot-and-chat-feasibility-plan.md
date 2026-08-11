# Framewrite — reposition as a document workflow tool + chat-with-video feasibility

## Context
A user told the founder Framewrite reads more like "document workflow management" than a one-shot "video → document converter," and the founder likes that framing. Separately, the founder is considering a "chat with your video" feature and wants to know how much extra work it'd take. This plan (a) recommends concrete messaging/positioning changes to lean into the workflow framing, grounded in features that already exist but aren't marketed as such, and (b) scopes chat-with-video against the actual codebase so the effort estimate is real, not guessed.

**Key finding that ties both asks together:** the cheapest way to make "chat with video" real is to let users chat with the *document* Framewrite already produces (`document.md`) — which is exactly the "living document you keep working with" story the workflow pivot wants to tell. They reinforce each other rather than being two separate asks.

## Part A — Positioning: "document workflow," not "one-shot converter"

**Why the current framing reads as a converter:** `Hero.astro`'s headline is "Turn any video into a document you'll actually use" — pure input→output framing. Nothing on the homepage today mentions the parts of the product that are genuinely workflow-shaped:
- `FrameReviewPanel.tsx` / `routes/review.py` — video jobs pause at `awaiting_review` so the user picks which frames make the document, before it's finalized. This is a real approve/refine step, not a black box.
- `TranscriptViewer.tsx` / `routes/transcript.py` — speaker rename after the fact, propagates into the doc/JSON/summary.
- `/documents` — a persistent, growing library across every job, not a single download-and-forget.
- Just shipped: in-app preview, shareable links, Drive export — a document that gets *used* after creation, not just handed off once.

None of this shows up in `FeatureGrid.astro` today, which lists generic capabilities (transcript, frame capture, formatting, search, export) but never mentions "you review and approve what goes in" — the actual workflow step.

**Recommended copy changes** (no backend changes, pure messaging):
- `marketing/src/components/Hero.astro` — shift the headline from a single conversion event to an ongoing process, e.g. lead with review/control rather than raw transcription. Something in the direction of: "Your recordings, turned into documents you review, refine, and keep using." (exact copy to be drafted, not prescribed here.)
- `marketing/src/components/FeatureGrid.astro` — add an item for the review/approval step (currently invisible in marketing despite being real, shipped, differentiated functionality) and reframe "Instantly searchable" toward the growing-library angle now that `/documents` and (per the earlier engagement-features pass) preview/share exist.
- Page `<title>`/meta descriptions across `index.astro`, `docs`, etc. — nudge toward "workflow" language for consistency once the homepage copy changes.

This is copy-only, low-risk, and reversible — good candidate to just execute.

## Part B — Chat with your video's document

**What already exists that this reuses directly:**
- `backend/app/stages/compose.py`'s `_get_client_and_fns(provider)` — already instantiates an Anthropic or OpenAI client depending on `settings.LLM_PROVIDER`. A chat feature reuses this exact pattern instead of adding new provider plumbing.
- The canonical artifact to chat against is `document.md` (`_owned_done_doc_dir` in `routes/documents.py`), which exists uniformly for **both** video and audio jobs. The raw transcript (`transcript.json`) is only persisted for **audio** jobs today (`pipeline.py`'s `run_job`) — video jobs never write it. Chatting against the composed document instead of the raw transcript sidesteps that asymmetry entirely and needs no pipeline change.
- Duration caps (90 min video default, `MAX_DURATION_SECONDS`) keep a composed document well within any modern LLM's context window (tens of thousands of tokens at most) — **no RAG/embeddings/vector store needed for v1**. The whole document is just stuffed into the prompt each time, and Claude's prompt caching (already the default provider) makes repeat cost per follow-up message cheap.

**New work required:**
- Backend: one new table (`chat_messages`: id, job_id, role, content, created_at — same shape/size as the `Testimonial`/`Feedback` tables already in this repo), a small `app/chat.py` data module, and `app/routes/chat.py` with `POST /api/jobs/{id}/chat` (owner-only, loads `document.md`, sends system prompt + history + new message to the LLM, persists both turns, returns the reply) and `GET /api/jobs/{id}/chat` (history). Register in `main.py`. One migration.
- Frontend: a `ChatPanel.tsx` (message list + input, calls the two endpoints) added to the job detail page, gated on `status === "done"`. Plain request/response is fine for v1 — no streaming needed.
- Decisions to make before building (not code, just calls to make):
  1. **Owner-only for v1** — do not expose chat on the public share link (`/share/[token]`); anyone with a link could otherwise run up LLM spend with no rate limit tied to an account.
  2. **Abuse/cost control** — cap messages per job (e.g. a fixed number per day) since this is the one feature that costs real LLM money per user action, unlike the flat-rate pipeline pricing.
  3. **No billing integration in v1** — treat it as included/free initially rather than wiring wallet charges per message; revisit if usage is meaningful.

**Effort, relative to work already in this repo (no invented hours):** smaller than the Google Drive integration (which needed OAuth + encrypted token storage) and about the same size as the shareable-link feature shipped in the last session (one migration, one new route module, one new frontend panel) — except simpler, since chat doesn't need a public/tokenless variant for v1. The real work is the three decisions above, not the plumbing.

## Decision
**Implementing now:** Part A, the positioning pivot (copy-only, `Hero.astro` + `FeatureGrid.astro`).
**Not building yet:** Part B, chat-with-video — stays scoped as an estimate in this doc for later.

### Part A execution plan
- `marketing/src/components/Hero.astro` — replace the headline `"Turn any video into<br/>a document<br/><em>you'll actually use.</em>"` and the `.hero-sub` paragraph. New framing leads with the workflow (upload → review/approve → refined document you keep using) instead of a single conversion event, while still naming the concrete mechanics (transcript, speaker labels, images) so it doesn't go vague. Keep the existing visual structure (eyebrow, h1, hero-sub, actions, transcript-sample, fineprint) — only the copy changes, not the layout/CSS.
- `marketing/src/components/FeatureGrid.astro` — add one new item to the `items` array (currently 8 items ending with "Audio-only transcripts") for the review/approval step, e.g. title "You approve what makes it in" / body describing that video jobs pause for the user to pick which slides/diagrams get included before the document is finalized (matches `FrameReviewPanel.tsx` / `awaiting_review` behavior in `backend/app/routes/review.py`). Place it early in the list (right after the transcript/frame-capture items) since it's the crux of the "workflow, not one-shot" argument — not buried at the end.
- Leave `MarketingLayout`/page `<title>`/meta description changes for a later pass once the new copy direction is settled and proven, rather than propagating a first-draft headline into SEO metadata immediately.

**Verify:** `cd marketing && npm run build` (catch any build errors), then `npm run dev` and visually check the Hero and FeatureGrid sections in both light and dark mode, at the existing breakpoints (900px for Hero's grid, 780px for FeatureGrid's index-item grid) — same verification pattern used for every marketing change earlier in this project.

### Part B (unchanged — reference only, not building now)
When greenlit later, build order: migration for `chat_messages` → `app/chat.py` → `app/routes/chat.py` (owner-only `POST`/`GET /api/jobs/{id}/chat`, reusing `_get_client_and_fns`-style LLM client setup and `document.md` as context) → register in `main.py` → `ChatPanel.tsx` on the job detail page. Decide the three open calls (owner-only scope, per-job rate limit, no billing in v1) before writing code, not during.
