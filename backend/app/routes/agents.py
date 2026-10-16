"""AI agents (proof of concept): a user-assembled agent made of a knowledge
base of their finished documents, tools and skills picked from a pre-made
catalog, and memory from earlier conversations. See app/agents.py for the
logic and app/agent_catalog.py for the catalog.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import agent_catalog, agents, jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def _owned_agent(agent_id: str, current_user: dict) -> dict:
    agent = agents.get_agent(agent_id)
    if not agent or agent["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _validate_catalog_ids(tool_ids: list[str], skill_ids: list[str]) -> None:
    if not all(agent_catalog.is_valid_tool(t) for t in tool_ids):
        raise HTTPException(status_code=400, detail="Unknown tool")
    if not all(agent_catalog.is_valid_skill(s) for s in skill_ids):
        raise HTTPException(status_code=400, detail="Unknown skill")


def _attach_job(agent_id: str, job_id: str, current_user: dict) -> dict | None:
    """Snapshots a finished document into the agent's knowledge base. Same
    ownership/state rules as routes/documents.py's _owned_done_doc_dir
    (404 rather than leaking whether someone else's job exists)."""
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"] or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Document not found")
    if job["job_type"] not in ("video", "audio"):
        raise HTTPException(status_code=400, detail="Only video and audio documents can be attached")
    if job["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail="This document was deleted after 7 days per the retention policy")
    title = job["title"] or "Untitled document"
    doc_dir = (settings.OUTPUT_DIR / job_id / "document").resolve()
    content = agents.build_snapshot(doc_dir, title)
    return agents.attach_document(agent_id, job_id, title, content)


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    instructions: str = Field(default="", max_length=4000)
    tool_ids: list[str] = []
    skill_ids: list[str] = []
    job_ids: list[str] = []


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    instructions: str | None = Field(default=None, max_length=4000)
    tool_ids: list[str] | None = None
    skill_ids: list[str] | None = None


class AttachDocumentRequest(BaseModel):
    job_id: str


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@router.get("/api/agents/catalog")
def get_catalog(current_user: dict = Depends(get_current_user)) -> dict:
    return agent_catalog.catalog()


@router.get("/api/agents")
def list_agents(current_user: dict = Depends(get_current_user)) -> dict:
    return {"agents": agents.list_agents(current_user["id"])}


@router.post("/api/agents", status_code=201)
def create_agent(body: AgentCreateRequest, current_user: dict = Depends(get_current_user)) -> dict:
    _validate_catalog_ids(body.tool_ids, body.skill_ids)
    # Validate every job before creating anything, so a bad job_id doesn't
    # leave a half-built agent behind.
    for job_id in body.job_ids:
        job = jobs.get_job(job_id)
        if not job or job["user_id"] != current_user["id"] or job["status"] != "done" or job["deleted_at"] is not None:
            raise HTTPException(status_code=404, detail="Document not found")
    agent = agents.create_agent(current_user["id"], body.name.strip(), body.instructions, body.tool_ids, body.skill_ids)
    for job_id in dict.fromkeys(body.job_ids):
        _attach_job(agent["id"], job_id, current_user)
    return agent


@router.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    agent = _owned_agent(agent_id, current_user)
    agent.pop("user_id")
    return {**agent, "documents": agents.list_documents(agent_id)}


@router.patch("/api/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentUpdateRequest, current_user: dict = Depends(get_current_user)) -> dict:
    _owned_agent(agent_id, current_user)
    fields = body.model_dump(exclude_none=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    _validate_catalog_ids(fields.get("tool_ids", []), fields.get("skill_ids", []))
    return agents.update_agent(agent_id, **fields)


@router.delete("/api/agents/{agent_id}", status_code=204)
def delete_agent(agent_id: str, current_user: dict = Depends(get_current_user)) -> None:
    _owned_agent(agent_id, current_user)
    agents.delete_agent(agent_id)


@router.post("/api/agents/{agent_id}/documents", status_code=201)
def attach_document(
    agent_id: str, body: AttachDocumentRequest, current_user: dict = Depends(get_current_user)
) -> dict:
    _owned_agent(agent_id, current_user)
    doc = _attach_job(agent_id, body.job_id, current_user)
    if doc is None:
        raise HTTPException(status_code=409, detail="This document is already attached")
    return doc


@router.delete("/api/agents/{agent_id}/documents/{doc_id}", status_code=204)
def remove_document(agent_id: str, doc_id: str, current_user: dict = Depends(get_current_user)) -> None:
    _owned_agent(agent_id, current_user)
    if not agents.remove_document(agent_id, doc_id):
        raise HTTPException(status_code=404, detail="Document not found")


@router.delete("/api/agents/{agent_id}/memory", status_code=204)
def clear_memory(agent_id: str, current_user: dict = Depends(get_current_user)) -> None:
    _owned_agent(agent_id, current_user)
    agents.clear_memory(agent_id)


@router.get("/api/agents/{agent_id}/conversations")
def list_conversations(agent_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    _owned_agent(agent_id, current_user)
    return {"conversations": agents.list_conversations(agent_id)}


@router.post("/api/agents/{agent_id}/conversations", status_code=201)
def start_conversation(agent_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    """Also folds the previous conversation into the agent's memory (see
    agents.start_conversation), so this call can take a few seconds."""
    agent = _owned_agent(agent_id, current_user)
    conversation = agents.start_conversation(agent)
    return {**conversation, "memory": agent["memory"]}


@router.get("/api/agents/{agent_id}/conversations/{conversation_id}/messages")
def list_messages(agent_id: str, conversation_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    _owned_agent(agent_id, current_user)
    if not agents.conversation_belongs_to(agent_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"messages": agents.list_messages(conversation_id)}


@router.post("/api/agents/{agent_id}/conversations/{conversation_id}/messages")
def post_message(
    agent_id: str, conversation_id: str, body: MessageRequest, current_user: dict = Depends(get_current_user)
) -> dict:
    agent = _owned_agent(agent_id, current_user)
    if not agents.conversation_belongs_to(agent_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        agents.check_rate_limit(current_user["id"])
    except agents.AgentRateLimitedError:
        raise HTTPException(status_code=429, detail="Too many messages too quickly -- please wait a few minutes")
    try:
        return agents.post_message(agent, conversation_id, body.message)
    except agents.AgentUnavailableError:
        raise HTTPException(status_code=503, detail="Agents are temporarily unavailable -- no LLM provider configured")
    except Exception:
        raise HTTPException(status_code=502, detail="Could not get an answer -- please try again")
