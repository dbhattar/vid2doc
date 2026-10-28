# Choose a transformation when submitting a video

## Context
Today every video becomes one thing: a full, LLM-rewritten document (`pipeline._compose_and_finalize` -> `compose.compose_document`). Users should pick what they get from the same video:

| Transformation | id | Output |
|---|---|---|
| Full document (today) | `document` | unchanged, frames optional |
| Concise notes | `notes` | bullet notes, each with a timestamp link, plus a "Further reading" section of external links |
| Study guide | `study_guide` | learning objectives, key concepts and definitions, a summary, review questions with answers |
| Deeper research | `research` | topics extracted from the video, researched on the web, written up as a report with cited sources |

Decisions (from user): include research in v1; notes get both timestamp links and web links; same $1/hr rate as video for document/notes/study guide; notes/study guide/research are text-only (no frame extraction, so no `awaiting_review` pause).

Key finding: everything downstream (`_finalize_document`, chat, share, Drive, agents, email) only needs `title` + `sections` + `document.md` + `transcript.json`. So each new transformation is a new compose step that returns the same `sections` shape. The seam is `pipeline._compose_and_finalize` (pipeline.py:244-257).

## Backend

1. **Column**: `Job.transformation` String, default `"document"` (models.py, near `extract_frames`). Migration `0026_job_transformation.py` (`down_revision="0025"`, `server_default="document"`, modeled on 0023). Add it to `jobs._job_to_dict` and `jobs.create_job`, and expose it from `routes/status.py:build_job_response` for video jobs.
2. **Submit routes**: add `transformation: str = Form("document")` to `routes/convert.py` and the body model in `routes/youtube.py`. Validate against `TRANSFORMATIONS`, 400 otherwise. For anything but `document`, force `extract_frames=False`, and reject `make_public=True` with 400 (public showcase is built around full documents).
3. **Billing**: add one helper in `billing.py`, `billing_type_for(job_type, extract_frames, transformation)`, replacing the three hand-rolled derivations (`convert.py:50`, `youtube.py:59`, `routes/jobs.py:67-68`). Mapping: `document` -> existing logic; `notes` and `study_guide` -> `"video"` rate; `research` -> new `"research"` rate in `cost_for_duration_cents` (proposed `SECONDS_PER_CENT_RESEARCH = 18`, about $2/hr; placeholder to confirm, since it covers real web-search cost).
4. **Retry**: `routes/jobs.py:84-95` copies `transformation` to the new job and uses the helper, so a retry doesn't silently revert to a full document or re-bill at the wrong rate.
5. **New stage module `backend/app/stages/transform.py`**, reusing `compose._make_windows`, `compose._get_client_and_fns`-style provider switching (Anthropic tool_use / OpenAI json_schema) and the map-reduce shape of `generate_summary_and_key_points`:
   - `compose_notes(segments, source_url)`: per window, the LLM returns notes `[{heading, points: [{text, start_seconds}]}]`. **Code, not the model, renders timestamp links**: YouTube jobs get `[12:34](<source_url>&t=754s)`, uploads get a plain `(12:34)` marker, so URLs can't be hallucinated. Times are validated against the transcript range (reuse the approach in `chat_jobs.validate_citations`).
   - `compose_study_guide(segments)`: map-reduce, per window extract concepts/definitions/questions, then one final pass merges into objectives, key concepts, summary and Q&A.
   - `compose_research(segments)`: extract up to ~6 researchable topics, then web-search each.
   - Each returns `sections` as `{heading, blocks:[{type:"paragraph", text}]}` (paragraph text may contain markdown bullets/links), then `compose.generate_title` as today.
6. **Web research helper `backend/app/stages/web_research.py`**: batch twin of `agent_tools/research_topic.py` / `live_research.py` (OpenAI Responses API with the `web_search` tool, `settings.AGENT_OPENAI_MODEL`), returning `{summary, links:[{title,url}]}` per topic. OpenAI-only like those. If `OPENAI_API_KEY` is missing: `notes` skips "Further reading" (timestamp links still work), `research` fails the job with a clear `PipelineError` (and the existing refund path runs). Cap topics and results per job to bound cost.
7. **Pipeline**: in `_compose_and_finalize`, branch on `job["transformation"]`: for non-document, call the matching `transform.*` function (set `progress_stage="composing_document"`, and a new `"researching"` stage before web search), skip `_prepend_summary_section` (notes and guide carry their own summary), and still write `transcript.json` and call `_finalize_document` unchanged. `run_job` already takes the no-frames branch when `extract_frames` is false, so no review pause occurs.
8. **docx/pdf rendering** (`stages/assemble.py`, paragraph branches near lines 313 and 492): paragraph text is written verbatim, so markdown links and `- ` bullets would show as literal text in docx/pdf (they work in `document.md`). Add minimal inline handling: `[text](url)` becomes a hyperlink and leading `- ` becomes a bullet. Keep it small and shared between the docx and pdf paths.
9. **Chat, share, Drive, agent snapshots**: no changes (they read `document.md` + `transcript.json`). Chat answers draw on the notes/guide text plus the full transcript, which is fine. Update the chat system prompt wording only if testing shows confusion with non-document outputs.

## Frontend
1. `frontend/lib/jobs.ts`: `Transformation` type, `Job.transformation?`.
2. `frontend/app/(app)/dashboard/video/page.tsx`: a transformation selector (four radio cards with a one-line description each) next to the existing source picker. Send `transformation` in both the file FormData (`:121`) and YouTube JSON body (`:146`). Show the "extract frames" and "make public" options only for `document`. Show a small "uses web search" hint on research.
3. `frontend/app/(app)/dashboard/jobs/[id]/page.tsx:163-171`: badge/label per transformation ("Concise notes", "Study guide", "Research report") instead of only "Video document". Document preview and downloads already work for any `document.md`.
4. `frontend/lib/jobStages.ts`: add the `researching` stage to the video stage list.

## Out of scope
Audio uploads, live sessions and `video_gen` keep their current single behavior. Applying transformations to those, or re-transforming an already-finished job (reusing its transcript for a lower cost), are natural follow-ups.

## Verification
- `alembic upgrade head` locally (`./restart-containers.sh --dev`).
- Backend: unit-check the helpers (`billing_type_for` mapping, timestamp-link rendering for YouTube vs upload, timestamp clamping). Add a validation milestone script in `validation/` modeled on `milestone_5_billing.py` (charge/refund per transformation, retry keeps the transformation) and `milestone_4_document_bundle.py` (output files exist).
- End to end per transformation: submit a short video and a YouTube URL; confirm status reaches `done`, `document.md` has the expected structure, timestamp links open at the right second, docx/pdf render links/bullets, and no `awaiting_review` pause occurs. For `research`, check cited URLs resolve; with `OPENAI_API_KEY` unset, confirm the job fails cleanly and refunds.
- Frontend: `npm test`, typecheck and lint; manually check the selector, hidden options, labels, and retry.
- Per repo convention, save the approved plan to `plan/video-transformations-plan.md`.
