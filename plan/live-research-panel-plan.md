# Live research side panel for the Live page

## Context

The live transcription page currently does everything client-side (VAD,
ASR, diarization) and sends nothing to the backend until the user stops and
saves. The user wants an opt-in feature where, as a live session runs, a
side panel surfaces relevant background research on whatever topic is
currently being discussed — using the OpenAI API key already configured
for this project, specifically its web-search capability (confirmed this
backend has zero existing search/retrieval tooling today, only structured
LLM calls for document generation). Free to end users for now, with an
explicit acknowledgment that it costs real OpenAI usage and will likely
need billing/limits later — so this plan includes a kill-switch flag and a
minimal rate limit, but deliberately no billing integration.

Confirmed via direct code reading (not assumed): this app has **zero
existing streaming/SSE/WebSocket precedent** anywhere, and **zero
persisted user-preference mechanism** (every opt-in toggle today, e.g.
`saveAudio`, is local `useState` that resets per session). Both of those
facts shape the design below — periodic one-shot request/response calls,
not a new streaming mechanism, and a local-only checkbox, not a new
settings table.

## Backend — new endpoint

**`backend/app/routes/live.py`** (add to the existing file — it's already
the home for live-session HTTP concerns, and this has nothing to do with
the job-queue/worker system `stages/` serves):

```
POST /api/live/research
  body: { recent_text: string, covered_topics: string[] }
  → { note: { topic: string, body: string, links: {title,url}[] } | null }
```

- `recent_text`: the accumulated finalized-turn text since the last call
  (frontend-owned window, not a session the backend tracks — stateless,
  matching `saveAudio`'s "no persistence" precedent). Length-capped
  server-side.
- `covered_topics`: short labels of topics already surfaced this session,
  so the model doesn't repeat itself. Capped list length + item length.
- `note: null` is a real, expected response — the model should say "nothing
  new" rather than forcing a note every call. Design the OpenAI structured
  schema with `note` nullable (same pattern `stages/classify.py` already
  uses for nullable fields).

**New file `backend/app/live_research.py`**, mirroring `chat_jobs.py`'s
shape exactly (a synchronous, request-handler-scoped LLM call — not the
async batch-pipeline pattern in `stages/`):
- `class LiveResearchUnavailableError(Exception)` — raised when
  `OPENAI_API_KEY` is unset (OpenAI-only for this feature, no Anthropic
  fallback branch, since web search here is specifically an OpenAI
  capability).
- `get_research_note(recent_text: str, covered_topics: list[str]) -> dict | None`
  — one OpenAI call with web search enabled, returns the shaped note or
  `None`. **The exact OpenAI request shape (Responses API `web_search`
  tool vs. a dedicated search-enabled model vs. something newer) must be
  verified against current OpenAI docs at implementation time** — this
  plan does not commit to one, and the installed `openai` SDK version in
  `requirements.txt` may need bumping. Keep this function's signature as
  the stable boundary so the route/frontend never need to know which shape
  is used underneath.
- A minimal, proportionate rate limit: an in-process
  `dict[user_id, list[timestamp]]`, pruned to a rolling window (e.g. 10
  min), capped generously (e.g. 20 calls/10 min — well above what the
  frontend's own ~30s cadence would ever produce in a normal session).
  Raise a dedicated error → `HTTPException(429, ...)`. Explicitly a known
  limitation (resets on restart, doesn't coordinate across replicas) —
  fine for now, first thing to upgrade if usage grows.

Route handler (`live.py`): checks `settings.LIVE_RESEARCH_ENABLED` (503 if
off), validates `recent_text` non-empty, calls the rate limiter, then
`live_research.get_research_note(...)`, translating
`LiveResearchUnavailableError` → 503 and any other exception → 502 —
exactly `routes/chat.py`'s existing `post_chat_message` error-translation
pattern (confirmed verbatim: `except chat_jobs.ChatUnavailableError: raise HTTPException(503, ...)`).

**`backend/app/config.py`** — add directly below `PAYMENTS_ENABLED`,
same style:
```python
# Kill switch for the live-transcription "research" side panel (opt-in,
# see routes/live.py's POST /api/live/research) -- gates the endpoint
# outright (503) regardless of the frontend's own checkbox. Free to end
# users for now (no wallet charge -- see live_research.py's rate limiting
# for the only cost safety net in place); exists so this can be paused
# instantly if OpenAI web-search cost runs away, without a deploy.
LIVE_RESEARCH_ENABLED = os.environ.get("LIVE_RESEARCH_ENABLED", "true").strip().lower() != "false"
```
No new GET/flags endpoint — the frontend just reacts to a 503 on first
call by hiding/disabling the checkbox, same as any other `ApiError`.

No `Job`/ledger/billing involvement at all — confirmed the existing
`charge_for_job`/`charge_for_chat` model assumes a known cost computed up
front, which doesn't fit an open-ended live session; deliberately not
wired up here per explicit scope.

## Frontend — layout

**`frontend/app/(app)/dashboard/live/page.tsx`**, inside the existing
`<div className="mt-6 min-h-0 flex-1">` middle section:

- Research **off** (default): zero change — the exact current
  `mx-auto max-w-2xl` centered transcript card stays byte-for-byte.
- Research **on**: wrap transcript card + a new panel in a
  `flex h-full min-h-0 gap-6 flex-col lg:flex-row` row — transcript card
  drops its centering/max-width and becomes `flex-1`, research panel gets
  a fixed-ish width (`lg:w-80 xl:w-96`), both independently
  `min-h-0 overflow-y-auto` internally (same scroll pattern the transcript
  card already uses). Stacks vertically below `lg`.
- Panel internals mirror the transcript card: `shrink-0` header
  ("Research"), scrolling list of notes (topic label + body + link list),
  empty state "Listening for a topic to research..." before the first
  note (same convention as the transcript's own "Listening..." state).

## Frontend — opt-in, cadence, state

New state in `LivePage`, alongside existing `saveAudio`/`turns`:
```tsx
const [liveResearchEnabled, setLiveResearchEnabled] = useState(false); // mirrors saveAudio exactly
const [researchNotes, setResearchNotes] = useState<ResearchNote[]>([]);
const pendingResearchTextRef = useRef("");
const coveredTopicsRef = useRef<string[]>([]);
const researchInFlightRef = useRef(false);
```
`type ResearchNote = { topic: string; body: string; links: { title: string; url: string }[] }`.

- New checkbox next to `saveAudio` in the bottom controls bar, identical
  pattern: `disabled={status !== "idle"}`, plain local state, no
  persistence (out of scope, see below). Label makes the data-sending
  explicit: *"Show live research panel (sends recent transcript to our
  server)"*.
- In `onFinal` (where `turns` already gets appended), also append
  `turn.text` to `pendingResearchTextRef` when `liveResearchEnabled`.
- Cadence: a `useEffect` keyed on `status === "recording" && liveResearchEnabled`
  running a plain `setInterval` (no new debounce utility — none exists in
  this codebase, and this is one call site, not worth a generic hook; same
  "run on an interval while active" shape `lib/useElapsedSeconds.ts`
  already uses as precedent). Every ~30s: if enough new text has
  accumulated (a min-chars floor) and no call is already in flight, POST
  via `apiFetch` to `/api/live/research`, append the returned note (if
  non-null) to `researchNotes`, and fold its topic into
  `coveredTopicsRef`. Clear `pendingResearchTextRef` before the call
  resolves so new speech keeps accumulating during the round-trip.
  Failures are swallowed (secondary, best-effort feature — a missed
  research beat shouldn't interrupt recording), except routing through the
  existing `handleAuthError` for a 401.
- Reset `researchNotes`/`pendingResearchTextRef`/`coveredTopicsRef` in
  `handleStart`, alongside the existing `setTurns([])`/`setPartialText("")`.
  No special handling needed for pause/resume — the effect's own `status`
  dependency naturally stops/restarts the interval. Nothing extra on stop;
  notes are never sent to `/api/live/finalize` or saved anywhere.

## Frontend — privacy copy

The current unconditional sentence under the page header:
> "Speech recognition and speaker diarization run entirely on your device
> -- nothing but the finished transcript is sent anywhere, and only if you
> choose to save it."

becomes conditional on `liveResearchEnabled`: unchanged verbatim when off;
when on, replaced with copy disclosing that recent transcript snippets are
now sent to the server as you talk for the research lookup, while making
clear the finished transcript itself still only gets sent on save.

## Explicitly out of scope

- Wallet/billing integration for this feature (kill-switch + rate limit
  only, per explicit instruction to keep it free for now).
- Persisting the opt-in preference server-side — session-local like
  `saveAudio`.
- Any UI beyond a simple scrolling note list (no pin/dismiss/collapse/
  re-query).
- Saving or exporting research notes — not part of `/api/live/finalize`,
  gone when the session ends.
- Non-English support — system prompt/topic extraction/search targets
  English only, same explicit-limitation framing as the diarization-
  accuracy plan.
- A reusable debounce/cadence hook — stays inline in `page.tsx`.
- A dedicated feature-flags GET endpoint.
- Cross-process/horizontally-scaled rate limiting.
- Pinning the exact OpenAI web-search call shape (verify at implementation
  time, see above).

## Verification

- Backend: with `OPENAI_API_KEY` set, manually `curl -X POST
  localhost:8000/api/live/research` (with a valid bearer token) with a
  sample `recent_text` about a concrete topic and confirm a real,
  non-generic note comes back with at least one link; try a second call
  with unrelated filler text short of `MIN_CHARS_TO_TRIGGER`-equivalent
  content to confirm `note: null` is a reachable response, not just a
  theoretical schema branch. Set `LIVE_RESEARCH_ENABLED=false` and confirm
  a clean 503. Fire >20 requests in under 10 minutes and confirm the 429
  rate-limit path actually triggers.
- Frontend: `npx tsc --noEmit`, `npm run build:workers`, `npm run build`
  (this repo's established pattern for live-page changes). Manual smoke
  test on `/dashboard/live`: record with the checkbox off (confirm layout
  and copy are pixel-identical to today), then on (confirm the panel
  appears, a note shows up within one or two ~30s cycles while discussing
  a concrete topic, pausing/resuming doesn't break the cadence, and
  stopping/leaving the page doesn't error).
- As with the rest of this live-page work this session, I don't have
  browser/mic automation available — the interactive parts (panel
  appearing live, note quality/relevance, responsive stacking) need manual
  confirmation on your end.
