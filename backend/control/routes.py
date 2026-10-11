from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from core.auth import session_is_valid
from core.config import get_settings
from core.providers import ProviderError
from control.agent import Agent
from control.skills import SkillManifest
from control.telemetry import snapshot
from control.mail import configured

router = APIRouter(prefix="/api/control", tags=["command-center"])


def owner(request):
    if not session_is_valid(request, get_settings()):
        raise HTTPException(401, "Owner sign-in required")


def services(request):
    return request.app.state.control_store, request.app.state.scheduler


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: str | None = None
    request_id: str = Field(default_factory=lambda: uuid4().hex, max_length=128)


@router.get("/snapshot")
async def state(request: Request):
    store, scheduler = services(request)
    telemetry = await snapshot(get_settings())
    skills = store.skills()
    suggestions = []
    if telemetry["ram_percent"] > 85:
        suggestions.append(
            "System RAM is above 85%. Consider pausing background work before the next video job."
        )
    loaded = telemetry["ollama"].get("models", [])
    if loaded and not scheduler.active:
        suggestions.append(
            "The local model is resident. Release model memory when you want to prioritise video work."
        )
    pending = [j for j in store.jobs() if j["status"] == "awaiting_approval"]
    if pending:
        suggestions.append(
            f"{len(pending)} mission(s) need your approval before they can run."
        )
    return {
        "suggestions": suggestions,
        "telemetry": telemetry,
        "jobs": store.jobs(),
        "events": store.events(),
        "questions": store.questions(),
        "preferences": store.preferences(),
        "skills": [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "risk": s["risk"],
                "resources": s["resources"],
                "version": s["version"],
            }
            for s in skills
        ],
        "model": get_settings().ollama_model,
        "presence": store.setting("presence", "home"),
        "paused": store.setting("paused", False),
        "email_configured": configured(),
        "authenticated": session_is_valid(request, get_settings()),
        "capabilities": {
            "bundlebee": any(s["id"] == "bundlebee" for s in skills),
            "postgamelens": any(s["id"] == "postgamelens" for s in skills),
        },
    }


@router.post("/chat")
async def chat(body: Chat, request: Request):
    owner(request)
    store, scheduler = services(request)
    try:
        async with request.app.state.agent_lock:
            return await Agent(
                get_settings(), store, request.app.state.control_memory, scheduler
            ).chat(body.message, body.conversation_id, body.request_id)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


class Command(BaseModel):
    action: str
    value: str | int | bool | None = None


@router.post("/mode")
def mode(body: Command, request: Request):
    owner(request)
    store, _ = services(request)
    if body.action == "presence" and body.value in ("home", "away"):
        store.set_setting("presence", body.value)
    elif body.action == "paused" and isinstance(body.value, bool):
        store.set_setting("paused", body.value)
    else:
        raise HTTPException(400, "Unsupported setting")
    store.event("mode", body.action + " changed to " + str(body.value))
    return {"ok": True}


@router.post("/jobs/{jid}")
async def job_action(jid: str, body: Command, request: Request):
    owner(request)
    store, scheduler = services(request)
    job = store.job(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    if (
        body.action == "priority"
        and isinstance(body.value, int)
        and not isinstance(body.value, bool)
        and 1 <= body.value <= 9
    ):
        result = store.update_job(jid, priority=body.value)
    elif body.action == "approve" and job["status"] == "awaiting_approval":
        result = store.update_job(jid, status="queued", approved=1)
    elif body.action == "pause" and job["status"] == "queued":
        result = store.update_job(jid, status="paused")
    elif body.action == "resume" and job["status"] in (
        "paused",
        "interrupted",
        "failed",
    ):
        skill = next((s for s in store.skills() if s["id"] == job["skill"]), {})
        if job["attempts"] and not skill.get("idempotent") and not job["checkpoint"]:
            raise HTTPException(
                409,
                "Side effects are uncertain. Review the skill output; resuming requires a checkpoint or an idempotent skill.",
            )
        result = store.update_job(jid, status="queued", approved=1, error="")
    elif body.action == "cancel" and job["status"] in (
        "queued",
        "paused",
        "awaiting_approval",
        "interrupted",
        "failed",
    ):
        result = store.update_job(jid, status="cancelled")
    else:
        raise HTTPException(
            409,
            "Action unavailable in this state. Running jobs must reach a checkpoint; stopping the queue does not terminate them.",
        )
    store.event("job", body.action + ": " + job["title"])
    return result


@router.post("/skills")
def install(body: SkillManifest, request: Request):
    owner(request)
    store, _ = services(request)
    store.install(body.model_dump())
    return {"installed": True, "id": body.id}


class Preference(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)
    expires_at: str | None = None


@router.post("/preferences")
def preference(body: Preference, request: Request):
    owner(request)
    store, _ = services(request)
    if body.expires_at:
        try:
            expires = datetime.fromisoformat(body.expires_at)
            if not expires.tzinfo:
                raise ValueError("Timezone required")
            body.expires_at = expires.astimezone(timezone.utc).isoformat()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"id": store.preference(body.title, body.content, body.expires_at, body.id)}


@router.post("/questions/{qid}")
def answer(qid: str, body: Preference, request: Request):
    owner(request)
    store, _ = services(request)
    with store.db() as c:
        if not c.execute(
            "SELECT id FROM control_questions WHERE id=?", (qid,)
        ).fetchone():
            raise HTTPException(404, "Question not found")
        c.execute(
            "UPDATE control_questions SET answer=? WHERE id=?", (body.content, qid)
        )
    store.preference(body.title, body.content, body.expires_at)
    return {"ok": True}


@router.get("/history/{cid}")
def history(cid: str, request: Request):
    owner(request)
    return {"messages": request.app.state.control_memory.get_recent_messages(cid, 100)}


@router.post("/unload")
async def unload(request: Request):
    owner(request)
    import httpx

    async with request.app.state.agent_lock:
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
                r = await client.post(
                    get_settings().ollama_base_url + "/api/generate",
                    json={"model": get_settings().ollama_model, "keep_alive": 0},
                )
                r.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Ollama could not unload the model") from exc
    return {"ok": True}


@router.post("/backup")
def backup(request: Request):
    owner(request)
    store, _ = services(request)
    import sqlite3

    destination = (
        Path(store.path).parent
        / "backups"
        / (
            "jarvis-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            + "-"
            + uuid4().hex[:6]
            + ".db"
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with store.db() as source, sqlite3.connect(destination) as target:
        source.backup(target)
    store.event("backup", "Database backup created")
    return {"path": str(destination)}


class Knowledge(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100000)


@router.post("/knowledge")
def knowledge(body: Knowledge, request: Request):
    owner(request)
    memory = request.app.state.control_memory.create_memory(
        "project", body.title, body.content, source="owner-document"
    )
    request.app.state.control_store.event("memory", "Knowledge added: " + body.title)
    return {"id": memory["id"]}


@router.get("/skill-templates/bundlebee")
def bundlebee_template(request: Request):
    owner(request)
    import sys

    return SkillManifest(
        id="bundlebee",
        name="Bundlebee catalogue audit",
        version="1.0.0",
        description="Read-only link validation of the owner-configured Bundlebee public catalogue. Does not publish products, verify prices or generate affiliate clicks.",
        transport="command",
        command=[
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "adapters" / "bundlebee.py"),
        ],
        input_schema={
            "type": "object",
            "properties": {
                "task": {"type": "string", "enum": ["link_validation"]},
                "max_items": {"type": "integer", "minimum": 1, "maximum": 100},
                "dry_run": {"type": "boolean", "const": True},
            },
            "required": ["task", "max_items", "dry_run"],
            "additionalProperties": False,
        },
        resources=["cpu"],
        risk="approval",
        idempotent=True,
        timeout_seconds=1200,
        success_schema={
            "type": "object",
            "properties": {
                "ok": {"const": True},
                "verified": {"const": True},
                "findings": {"type": "array"},
            },
            "required": ["ok", "verified", "findings"],
        },
    ).model_dump()
