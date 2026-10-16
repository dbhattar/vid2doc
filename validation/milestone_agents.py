"""Verifies the AI agents proof of concept (see plan/agents-plan.md).

Exercises: catalog, agent CRUD + ownership isolation, snapshotting a done
job's document into the knowledge base (and that the agent still has it after
the job's local files are deleted, like retention.py does), the tool-calling
loop (OpenAI is faked -- the only mock besides Google auth), and memory being
written when a new conversation starts. Run from the repo root:

    python validation/milestone_agents.py
"""

import json
import shutil
import types
import uuid
from unittest.mock import patch

from sqlalchemy import text

from common import auth_header, client, login_as, reset_test_user, settings
from app import agents as agents_logic
from app import jobs
from app.db import get_session


def cleanup(email: str) -> None:
    session = get_session()
    try:
        params = {"email": email}
        agent_ids = "SELECT id FROM agents WHERE user_id = (SELECT id FROM users WHERE email = :email)"
        convo_ids = f"SELECT id FROM agent_conversations WHERE agent_id IN ({agent_ids})"
        session.execute(text(f"DELETE FROM agent_messages WHERE conversation_id IN ({convo_ids})"), params)
        session.execute(text(f"DELETE FROM agent_conversations WHERE agent_id IN ({agent_ids})"), params)
        session.execute(text(f"DELETE FROM agent_documents WHERE agent_id IN ({agent_ids})"), params)
        session.execute(text(f"DELETE FROM agents WHERE user_id = (SELECT id FROM users WHERE email = :email)"), params)
        session.commit()
    finally:
        session.close()
    reset_test_user(email)


for e in ("alice-agents@example.com", "bob-agents@example.com"):
    cleanup(e)

alice = login_as("google-sub-alice-agents", "alice-agents@example.com", "Alice")
bob = login_as("google-sub-bob-agents", "bob-agents@example.com", "Bob")
ah, bh = auth_header(alice["access_token"]), auth_header(bob["access_token"])
alice_id = alice["user"]["id"]


def make_done_job(user_id: str, title: str, body: str) -> str:
    job_id = str(uuid.uuid4())
    jobs.create_job(job_id, None, user_id=user_id, title=title, job_type="video")
    jobs.update_job(job_id, status="done")
    doc_dir = settings.OUTPUT_DIR / job_id / "document"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "document.md").write_text(body)
    (doc_dir / "transcript.json").write_text(
        json.dumps({"segments": [{"start_ts": 5, "end_ts": 9, "speaker": "Ann", "text": "We agreed the launch is Friday."}]})
    )
    return job_id


job_id = make_done_job(alice_id, "Launch sync", "# Launch sync\n\nThe quarterly budget is 5000 dollars.\n\nUnrelated closing remarks.")

# --- catalog ---
r = client.get("/api/agents/catalog", headers=ah)
assert r.status_code == 200, r.text
cat = r.json()
assert {t["id"] for t in cat["tools"]} == {"search_documents", "web_search", "research_topic"}, cat
assert {s["id"] for s in cat["skills"]} == {"meeting_summarizer", "study_guide"}, cat
print("Catalog lists the pre-made tools and skills OK")

# --- create ---
r = client.post("/api/agents", headers=ah, json={"name": "Launch bot", "tool_ids": ["nope"]})
assert r.status_code == 400, r.text
r = client.post("/api/agents", headers=ah, json={"name": "Launch bot", "job_ids": [str(uuid.uuid4())]})
assert r.status_code == 404, r.text
assert client.get("/api/agents", headers=ah).json()["agents"] == []
print("Unknown tool -> 400, unknown document -> 404, and neither leaves a half-built agent OK")

r = client.post(
    "/api/agents",
    headers=ah,
    json={"name": "Launch bot", "instructions": "Be brief", "tool_ids": ["search_documents"], "skill_ids": ["study_guide"], "job_ids": [job_id]},
)
assert r.status_code == 201, r.text
agent_id = r.json()["id"]
detail = client.get(f"/api/agents/{agent_id}", headers=ah).json()
assert [d["job_id"] for d in detail["documents"]] == [job_id] and detail["memory"] == "", detail
print("Create agent with a snapshotted document OK")

# --- ownership ---
assert client.get(f"/api/agents/{agent_id}", headers=bh).status_code == 404
assert client.post(f"/api/agents/{agent_id}/conversations", headers=bh).status_code == 404
assert client.get("/api/agents", headers=bh).json()["agents"] == []
bob_job = make_done_job(bob["user"]["id"], "Bob's", "secret")
assert client.post(f"/api/agents/{agent_id}/documents", headers=bh, json={"job_id": bob_job}).status_code == 404
assert client.post(f"/api/agents/{agent_id}/documents", headers=ah, json={"job_id": bob_job}).status_code == 404
assert client.post(f"/api/agents/{agent_id}/documents", headers=ah, json={"job_id": job_id}).status_code == 409
print("Per-user isolation (agents, other users' jobs) and duplicate-attach 409 OK")

# --- retention: delete the job's local files; agent must still know the document ---
shutil.rmtree(settings.OUTPUT_DIR / job_id)
snapshot = agents_logic._load_document_contents(agent_id)
assert "5000 dollars" in snapshot[0]["content"] and "launch is Friday" in snapshot[0]["content"], snapshot
print("Knowledge base survives the source files being deleted OK")


# --- tool loop with a faked OpenAI client ---
class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        N = types.SimpleNamespace
        if "previous_response_id" in kw:
            return N(id="r2", output=[], output_text="The budget is 5000 dollars.")
        if kw["instructions"].startswith("You maintain a short memory"):
            return N(id="m", output=[], output_text="- Cares about the Q3 budget")
        return N(
            id="r1",
            output=[N(type="function_call", name="search_documents", call_id="c1", arguments=json.dumps({"query": "budget"}))],
            output_text="",
        )


fake = types.SimpleNamespace(responses=FakeResponses())
with patch.object(agents_logic, "_get_client", return_value=fake):
    convo = client.post(f"/api/agents/{agent_id}/conversations", headers=ah).json()
    r = client.post(
        f"/api/agents/{agent_id}/conversations/{convo['id']}/messages", headers=ah, json={"message": "What is the budget?"}
    )
    assert r.status_code == 200, r.text
    reply = r.json()
    assert reply["content"] == "The budget is 5000 dollars." and reply["tools_used"] == ["search_documents"], reply
    tool_output = fake.responses.calls[1]["input"][0]["output"]
    assert "5000 dollars" in tool_output and "Unrelated closing" not in tool_output, tool_output
    assert "Study guide" in fake.responses.calls[0]["instructions"] and "Be brief" in fake.responses.calls[0]["instructions"]
    msgs = client.get(f"/api/agents/{agent_id}/conversations/{convo['id']}/messages", headers=ah).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"], msgs
    print("Agent called search_documents, answered from the snapshot, persisted messages OK")

    # --- memory: starting a new conversation folds the previous one in ---
    convo2 = client.post(f"/api/agents/{agent_id}/conversations", headers=ah).json()
    assert convo2["id"] != convo["id"]
    memory = client.get(f"/api/agents/{agent_id}", headers=ah).json()["memory"]
    assert memory == "- Cares about the Q3 budget", memory
    fake.responses.calls.clear()
    client.post(f"/api/agents/{agent_id}/conversations/{convo2['id']}/messages", headers=ah, json={"message": "hi"})
    assert "Cares about the Q3 budget" in fake.responses.calls[0]["instructions"]
    print("Memory written on new conversation and injected into the next system prompt OK")

# conversation from another agent/user can't be used
assert client.get(f"/api/agents/{agent_id}/conversations/{convo['id']}/messages", headers=bh).status_code == 404

# --- clear memory, update, delete ---
assert client.delete(f"/api/agents/{agent_id}/memory", headers=ah).status_code == 204
assert client.get(f"/api/agents/{agent_id}", headers=ah).json()["memory"] == ""
r = client.patch(f"/api/agents/{agent_id}", headers=ah, json={"tool_ids": ["search_documents", "web_search"]})
assert r.status_code == 200 and r.json()["tool_ids"] == ["search_documents", "web_search"], r.text
assert client.delete(f"/api/agents/{agent_id}", headers=ah).status_code == 204
assert client.get(f"/api/agents/{agent_id}", headers=ah).status_code == 404
print("Clear memory / update / delete OK")

# --- no key configured -> 503, not a crash ---
agent2 = client.post("/api/agents", headers=ah, json={"name": "No key"}).json()
convo3 = client.post(f"/api/agents/{agent2['id']}/conversations", headers=ah).json()
with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
    r = client.post(f"/api/agents/{agent2['id']}/conversations/{convo3['id']}/messages", headers=ah, json={"message": "hi"})
assert r.status_code == 503, r.text
print("Missing OPENAI_API_KEY -> 503 OK")

for e in ("alice-agents@example.com", "bob-agents@example.com"):
    cleanup(e)
print("\nAll agent checks passed.")
