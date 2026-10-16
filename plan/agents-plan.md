# AI Agents (proof of concept)

## Context
Users already turn video/audio into documents and can chat with a single document. We want to show that a user can assemble an **agent** from four parts: a **knowledge base** (their finished documents), **tools** (picked from a pre-made catalog), **memory** (carried across conversations), and **skills** (picked from a pre-made catalog) — then chat with it. This is a deliberately small PoC; catalogs live in code, and scaling (more tools/skills, user-defined ones, retrieval, billing) comes after the concept is proven.

Decisions made with the user: knowledge base is **snapshotted into the DB on attach** (local files are deleted after 7 days by `retention.py`); agent messages are **free** for now (guarded by a rate limit + turn cap); the first catalog is search documents, web search, research topic, meeting-summarizer skill, study-guide/quiz skill.

## Design

### Data model (new migration `backend/alembic/versions/0020_agents.py`, template: `0018_chat_with_document.py`; models added to `backend/app/models.py`)
- `agents`: id (str uuid), user_id (UUID, FK users), name, instructions (Text, the user's custom prompt), tool_ids (JSON list), skill_ids (JSON list), memory (Text, rolling summary), created_at, updated_at.
- `agent_documents`: id, agent_id FK, job_id (str, not FK, same convention as `related_job_id`), title, content (Text: `document.md` plus formatted transcript, snapshotted), created_at. Unique (agent_id, job_id).
- `agent_conversations`: id, agent_id FK, created_at, summarized_at (nullable).
- `agent_messages`: id, conversation_id FK, role, content (Text), tools_used (JSON, assistant only, for UI transparency), created_at.

### Catalogs (`backend/app/agent_catalog.py`, plain dicts, no DB)
- **Skills** = `{id, name, description, prompt}`; the prompt is appended to the system prompt. Start with `meeting_summarizer` (decisions, action items, owners) and `study_guide` (key concepts, quiz questions).
- **Tools** = `{id, name, description, schema, run(ctx, args)}`:
  - `search_documents` (+ companion `read_document`): keyword search over the agent's snapshots, returns snippets with doc title and timestamp; read returns a document truncated to a cap. Preselected in the UI. The system prompt lists attached documents (id, title) only, so many documents don't blow the context.
  - `web_search`: OpenAI's built-in `{"type": "web_search"}` tool passed through in the Responses API `tools` list (same tool type `live_research.py` already uses).
  - `research_topic(topic)`: a sub-call that takes the topic plus the relevant document excerpt, uses web search, and returns a short grounded note with links (same intent as `live_research.py`; implemented as a nested Responses API call with `web_search`).

### Agent loop (`backend/app/agents.py`)
- **OpenAI-only for the PoC** (the user has an OpenAI key; `OPENAI_API_KEY` read from `os.environ` at call time as elsewhere, missing key → `ChatUnavailableError`-style 503). Use the **Responses API** (`client.responses.create`, as `live_research.py` does) because it mixes built-in `web_search` with our own function tools in one call. Loop: send `input` + `tools` (function tools with JSON schemas + `web_search`); if the output contains `function_call` items, run each tool, append the output items plus `{"type": "function_call_output", "call_id", "output"}` to `input`, and call again; stop when there are none or after ~6 turns. Model from a new `settings.AGENT_OPENAI_MODEL` (default `settings.OPENAI_MODEL`). **Check the current Responses API function-calling shape in OpenAI's docs before coding**, as `live_research.py` itself warns this API moves fast.
- System prompt = base prompt + user instructions + selected skills' prompts + document index + `memory`.
- Persist only user text and final assistant text plus `tools_used`; tool traces are not stored.
- Rate limit: copy `live_research.check_rate_limit` (in-process, per user).

### Memory
Starting a **new conversation** summarizes the previous conversation with one small LLM call and merges it into `agents.memory`, which is injected into every later system prompt. Shown read-only on the agent page, with a "clear memory" button.

### API (`backend/app/routes/agents.py`, registered in `backend/app/main.py`)
Ownership via a `_owned_agent` helper that 404s, same as `chat.py:_owned_job`; auth via `get_current_user`.
- `GET /api/agents/catalog`; `GET/POST /api/agents`; `GET/PATCH/DELETE /api/agents/{id}`
- `POST /api/agents/{id}/documents {job_id}` (job must be the user's, `status=done`, `deleted_at` null, video/audio; reads `OUTPUT_DIR/<job_id>/document/document.md` + `transcript.json` as in `routes/documents.py:_owned_done_doc_dir`); `DELETE /api/agents/{id}/documents/{doc_id}`
- `GET/POST /api/agents/{id}/conversations`, `GET/POST /api/agents/{id}/conversations/{cid}/messages`
- `DELETE /api/agents/{id}/memory`

### Frontend (`frontend/`; read `node_modules/next/dist/docs/` first per `frontend/AGENTS.md`)
- `lib/agents.ts`: types + API calls via `apiFetch`. No streaming (matches `ChatPanel`).
- `components/Sidebar.tsx`: add "Agents" to `PRIMARY_NAV_LINKS`; new icon in `components/icons.tsx`.
- `app/(app)/agents/page.tsx` (list + empty state), `agents/new/page.tsx` (name, instructions, document checkboxes from `GET /api/jobs?status=done`, tool and skill checkboxes), `agents/[id]/page.tsx` (chat, attached documents, memory panel).
- `components/AgentChat.tsx`: adapted from `ChatPanel.tsx` (no citation button; shows a "used: web_search" chip per assistant message).
- Reuse `Card`, `Button`/`buttonClassName`, `Pagination`, existing input classes.

## Out of scope (next phase)
Billing/metering, streaming, embeddings retrieval, user-defined tools/skills, sharing agents, Anthropic provider support, an agent API for API-key users.

## Verification
1. `./restart-containers.sh --dev`; confirm alembic `0020` applies on boot (and downgrade works).
2. Add `validation/milestone_agents.py` in the style of the existing milestone scripts: create agent, attach a done doc, ask a question answerable only from the doc, assert a `search_documents` call was made, confirm 404 for another user's agent/job, and confirm memory is written after starting a new conversation.
3. Manual in the UI: create an agent with the study-guide skill, ask for a quiz, ask a research question and see the web_search/research_topic chip, start a new conversation and check the agent recalls earlier context.
4. Delete the document's local files (simulate retention) and confirm the agent still answers from the snapshot.
5. After approval, copy this plan to `plan/agents-plan.md` in the repo (per AGENTS.md).
