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
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

from sqlalchemy import text

from common import auth_header, client, login_as, reset_test_user, settings
from app import agents as agents_logic
from app import agent_catalog, drive_connections, jobs, mailgun_client
from app.agent_tools import _net, email_me, fetch_url, save_to_drive
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
        session.execute(
            text("DELETE FROM google_drive_connections WHERE user_id = (SELECT id FROM users WHERE email = :email)"), params
        )
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
assert {t["id"] for t in cat["tools"]} == {"search_documents", "web_search", "research_topic", "fetch_url", "email_me", "save_to_drive"}, cat
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


# --- tool availability (per user) ---
by_id = {t["id"]: t for t in client.get("/api/agents/catalog", headers=ah).json()["tools"]}
assert by_id["search_documents"]["available"] and by_id["web_search"]["available"], by_id
assert not by_id["save_to_drive"]["available"] and "Drive" in by_id["save_to_drive"]["unavailable_reason"], by_id
assert not by_id["email_me"]["available"], by_id  # Mailgun isn't configured in this environment
r = client.post("/api/agents", headers=ah, json={"name": "x", "tool_ids": ["save_to_drive"]})
assert r.status_code == 400 and "Drive" in r.json()["detail"], r.text
with patch.object(settings, "MAILGUN_API_KEY", "k"), patch.object(settings, "MAILGUN_DOMAIN", "d"):
    by_id = {t["id"]: t for t in client.get("/api/agents/catalog", headers=ah).json()["tools"]}
    assert by_id["email_me"]["available"], by_id
print("Per-user tool availability and 400 on selecting an unavailable tool OK")

# --- SSRF guard ---
def blocked(url, resolves_to=None):
    with patch.object(_net.socket, "getaddrinfo", return_value=[(2, 1, 6, "", (resolves_to, 0))] if resolves_to else None) as g:
        if resolves_to is None:
            g.side_effect = lambda host, *a, **k: [(2, 1, 6, "", (host, 0))]
        try:
            _net.check_public_url(url)
        except _net.FetchError:
            return True
        return False


for url in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://10.0.0.5/",
            "http://192.168.1.1/", "http://[::ffff:127.0.0.1]/", "file:///etc/passwd", "ftp://example.com/", "http://224.0.0.1/"):
    assert blocked(url), url
assert blocked("http://example.com:8080/"), "non-standard port"
assert blocked("http://evil.example/", resolves_to="10.1.2.3"), "hostname resolving to a private IP"
assert not blocked("https://example.com/", resolves_to="93.184.216.34")
print("SSRF guard blocks loopback/metadata/private/mapped/non-http/odd-port/private-resolving hosts, allows public OK")


def fake_response(status=200, headers=None, body=b"", encoding="utf-8"):
    resp = MagicMock()
    resp.status_code, resp.headers, resp.encoding = status, headers or {}, encoding
    resp.is_redirect = status in (301, 302, 303, 307, 308)
    resp.iter_content.side_effect = lambda chunk_size: iter([body[i : i + chunk_size] for i in range(0, len(body), chunk_size)])
    return resp


def public_dns(host, *a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", 0))] if host == "example.com" else [(2, 1, 6, "", ("10.0.0.9", 0))]


html_page = b"<html><head><title>Hi</title><script>evil()</script></head><body><nav>menu</nav><p>Hello <b>world</b></p></body></html>"
ctx = {"documents": [], "client": None, "user": alice["user"]}
with patch.object(_net.socket, "getaddrinfo", side_effect=public_dns):
    with patch.object(_net.requests, "get", return_value=fake_response(headers={"Content-Type": "text/html; charset=utf-8"}, body=html_page)):
        out = fetch_url.run(ctx, {"url": "https://example.com/a"})
    assert "Hello world" in out and "evil()" not in out and "menu" not in out and out.startswith("<untrusted_content"), out
    # redirect from a public URL to a private host is stopped at the second hop
    hops = [fake_response(302, {"Location": "http://internal.example/"}), fake_response(body=b"secret")]
    with patch.object(_net.requests, "get", side_effect=hops) as get:
        out = fetch_url.run(ctx, {"url": "https://example.com/redir"})
    assert "isn't a public website" in out and get.call_count == 1, out
    # oversized body is truncated at the byte cap; wrong content type refused
    with patch.object(_net.requests, "get", return_value=fake_response(headers={"Content-Type": "text/plain"}, body=b"a" * 2_000_000)):
        out = fetch_url.run(ctx, {"url": "https://example.com/big"})
    assert len(out) < 11_000 and "[truncated]" in out, len(out)
    with patch.object(_net.requests, "get", return_value=fake_response(headers={"Content-Type": "application/pdf"}, body=b"%PDF")):
        assert "Unsupported content type" in fetch_url.run(ctx, {"url": "https://example.com/x.pdf"})
print("fetch_url: text extraction, redirect re-validation, size cap, content-type check OK")

# --- email_me: only ever to the logged-in user, rate limited ---
with patch.object(settings, "MAILGUN_API_KEY", "k"), patch.object(settings, "MAILGUN_DOMAIN", "d"), \
        patch.object(mailgun_client, "send_email", return_value=True) as send:
    out = email_me.run(ctx, {"subject": "Notes", "body": "line <b>1</b>", "to": "victim@example.com"})
    assert out == "Email sent to the user.", out
    assert send.call_args.args[0] == "alice-agents@example.com", send.call_args
    assert send.call_args.args[1].startswith("[Framewrite agent]") and "&lt;b&gt;" in send.call_args.args[3]
    for _ in range(email_me.MAX_PER_HOUR):
        email_me.run(ctx, {"subject": "s", "body": "b"})
    assert "limit reached" in email_me.run(ctx, {"subject": "s", "body": "b"})
assert email_me.run(ctx, {"subject": "s", "body": "b"}) == "Email isn't configured on this server."
print("email_me: recipient fixed to the user, HTML escaped, rate limit, unconfigured message OK")

# --- save_to_drive ---
assert "Connect Google Drive" in save_to_drive.run(ctx, {"title": "t", "content": "c"})
with patch.object(settings, "ENCRYPTION_KEY", Fernet.generate_key().decode()):
    drive_connections.save_connection(alice_id, "alice@gmail.com", "refresh-token", "drive.file")
fake_drive = MagicMock()
fake_drive.files.return_value.create.return_value.execute.return_value = {"id": "f1", "webViewLink": "https://docs.google.com/document/d/f1"}
with patch("app.routes.drive._load_drive_client", return_value=fake_drive):
    out = save_to_drive.run(ctx, {"title": "Quiz", "content": "Q1 ..."})
assert "https://docs.google.com/document/d/f1" in out, out
create_kwargs = fake_drive.files.return_value.create.call_args.kwargs
assert create_kwargs["body"] == {"name": "Quiz", "mimeType": "application/vnd.google-apps.document"}, create_kwargs
assert not fake_drive.files.return_value.delete.called and not fake_drive.files.return_value.update.called
by_id = {t["id"]: t for t in client.get("/api/agents/catalog", headers=ah).json()["tools"]}
assert by_id["save_to_drive"]["available"], by_id
print("save_to_drive: not-connected message, creates a new Doc (create-only), availability flips once connected OK")

# --- oversized tool results are capped before reaching the model ---
big = {"documents": [{"id": "d", "title": "T", "content": "word " * 50_000}], "client": None, "user": alice["user"]}
from app.agent_tools import search_documents  # noqa: E402
assert len(search_documents.read(big, {"document_id": "d", "offset": 0})) <= agents_logic.MAX_TOOL_RESULT_CHARS
print("Tool result size within the cap OK")

for e in ("alice-agents@example.com", "bob-agents@example.com"):
    cleanup(e)
print("\nAll agent checks passed.")
