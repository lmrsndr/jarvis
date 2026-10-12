from __future__ import annotations
import asyncio
import hashlib
import sys
import pytest
from fastapi.testclient import TestClient
from core.config import Settings
from core.providers import OllamaProvider
from control.store import Store
from control.agent import Agent
from control.scheduler import Scheduler
from control.skills import SkillManifest, execute_skill
from memory.db import MemoryDatabase
from plugins.installer import PluginInstaller, PluginInstallError


def state(tmp_path):
    db = MemoryDatabase(str(tmp_path / "state.db"))
    db.init()
    store = Store(db.path)
    store.init()
    return store, db


def manifest(**overrides):
    value = dict(
        id="test_skill",
        name="Test skill",
        version="1",
        description="Test",
        endpoint="http://127.0.0.1:9999/run",
        input_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
    )
    value.update(overrides)
    return SkillManifest(**value).model_dump()


def test_jobs_persist_deduplicate_and_require_approval(tmp_path):
    store, _ = state(tmp_path)
    first = store.enqueue("Task", "test_skill", {"count": 1}, request_id="same")
    second = store.enqueue("Task", "test_skill", {"count": 2}, request_id="same")
    assert first["id"] == second["id"]
    assert store.claim() is None
    store.update_job(first["id"], status="queued", approved=1)
    assert store.claim()["status"] == "running"
    reopened = Store(tmp_path / "state.db")
    reopened.init()
    assert reopened.job(first["id"])["status"] == "interrupted"


def test_queue_priority_and_future_schedule(tmp_path):
    store, _ = state(tmp_path)
    store.enqueue(
        "Future",
        "test_skill",
        {},
        priority=1,
        run_at="2099-01-01T00:00:00+00:00",
        approved=True,
    )
    low = store.enqueue("Low", "test_skill", {}, priority=8, approved=True)
    high = store.enqueue("High", "test_skill", {}, priority=2, approved=True)
    assert store.claim()["id"] == high["id"]
    assert store.claim()["id"] == low["id"]


def test_preference_edit_and_expiry(tmp_path):
    store, _ = state(tmp_path)
    pid = store.preference("Priority", "Original")
    store.preference("Priority", "New", preference_id=pid)
    store.preference("Temporary", "Expired", "2000-01-01T00:00:00+00:00")
    assert len(store.preferences()) == 1
    assert store.preferences()[0]["content"] == "New"


def test_skill_contract_rejects_invalid_transport_and_plaintext_remote():
    with pytest.raises(ValueError):
        manifest(transport="shell")
    with pytest.raises(ValueError):
        manifest(endpoint="http://example.com/run")
    with pytest.raises(ValueError):
        manifest(id="../escape")


def test_agent_validates_native_arguments_and_queues_review(tmp_path, monkeypatch):
    store, db = state(tmp_path)
    store.install(manifest())
    scheduler = Scheduler(store, Settings())
    replies = iter(
        [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "skill_test_skill",
                                "arguments": {"count": "1"},
                            }
                        }
                    ],
                }
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "skill_test_skill",
                                "arguments": {"count": 1},
                            }
                        }
                    ],
                }
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "Waiting for owner approval.",
                }
            },
        ]
    )

    async def fake(self, messages, tools):
        return next(replies)

    monkeypatch.setattr(OllamaProvider, "native_chat", fake)
    result = asyncio.run(Agent(Settings(), store, db, scheduler).chat("Run task"))
    assert result["traces"][0]["result"]["ok"] is False
    assert store.jobs()[0]["status"] == "awaiting_approval"
    assert len(store.jobs()) == 1


def test_agent_cannot_install_skills(tmp_path, monkeypatch):
    store, db = state(tmp_path)
    replies = iter(
        [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {"function": {"name": "skills_install", "arguments": {}}}
                    ],
                }
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "Owner installation required.",
                }
            },
        ]
    )

    async def fake(self, messages, tools):
        return next(replies)

    monkeypatch.setattr(OllamaProvider, "native_chat", fake)
    r = asyncio.run(
        Agent(Settings(), store, db, Scheduler(store, Settings())).chat("Install")
    )
    assert r["traces"][0]["result"]["ok"] is False
    assert not store.skills()


def test_command_skill_executes_without_shell_and_checks_success(tmp_path):
    store, _ = state(tmp_path)
    command = [
        sys.executable,
        "-c",
        'import json,sys; r=json.load(sys.stdin); print(json.dumps({"ok":True,"count":r["args"]["count"]}))',
    ]
    m = manifest(transport="command", command=command)
    job = store.enqueue("Test", "test_skill", {"count": 4})
    result = asyncio.run(execute_skill(m, job["args"], job))
    assert result == {"ok": True, "count": 4}
    m = manifest(
        transport="command",
        command=[sys.executable, "-c", 'print("{\\"ok\\": false}")'],
    )
    with pytest.raises(Exception):
        asyncio.run(execute_skill(m, job["args"], job))


def test_scheduler_reports_while_worker_active_and_does_not_duplicate(
    tmp_path, monkeypatch
):
    store, _ = state(tmp_path)
    job = store.enqueue(
        "Report", "test_skill", {}, report_at="2000-01-01T00:00:00+00:00"
    )
    scheduler = Scheduler(store, Settings())
    scheduler.active = job
    monkeypatch.setattr("control.scheduler.send_pending", lambda s: None)
    asyncio.run(scheduler.tick())
    asyncio.run(scheduler.tick())
    with store.db() as c:
        assert c.execute("SELECT COUNT(*) FROM control_outbox").fetchone()[0] == 1


def test_scheduler_retries_only_idempotent_skill(tmp_path, monkeypatch):
    store, _ = state(tmp_path)

    async def fail(*args):
        raise ValueError("Failed after possible side effect")

    monkeypatch.setattr("control.scheduler.execute_skill", fail)
    store.install(manifest(idempotent=False))
    job = store.enqueue(
        "No retry", "test_skill", {"count": 1}, approved=True, max_attempts=3
    )
    job = store.claim()
    asyncio.run(Scheduler(store, Settings()).execute(job))
    assert store.job(job["id"])["status"] == "failed"
    store.install(manifest(idempotent=True))
    retry = store.enqueue(
        "Retry", "test_skill", {"count": 1}, approved=True, max_attempts=3
    )
    asyncio.run(Scheduler(store, Settings()).execute(store.claim()))
    assert store.job(retry["id"])["status"] == "queued"


def test_zip_preview_cannot_overwrite_absolute_filename(tmp_path):
    sentinel = tmp_path / "sentinel.zip"
    sentinel.write_bytes(b"original")
    with pytest.raises(PluginInstallError):
        PluginInstaller(tmp_path).preview_package(b"not zip", str(sentinel))
    assert sentinel.read_bytes() == b"original"


def test_owner_api_blocks_mutations_without_login(tmp_path, monkeypatch):
    from main import app

    settings = Settings(
        memory_db_path=str(tmp_path / "api.db"),
        admin_password_hash=hashlib.sha256(b"test-owner").hexdigest(),
    )
    monkeypatch.setattr("main.settings", settings)
    monkeypatch.setattr("control.routes.get_settings", lambda: settings)
    monkeypatch.setattr("core.permissions.get_settings", lambda: settings)
    from core.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            assert (
                client.post("/api/control/skills", json=manifest()).status_code == 401
            )
            assert (
                client.post(
                    "/api/control/preferences", json={"title": "T", "content": "C"}
                ).status_code
                == 401
            )
            assert (
                client.post(
                    "/api/system/login", json={"password": "test-owner"}
                ).status_code
                == 200
            )
            assert (
                client.post("/api/control/skills", json=manifest()).status_code == 200
            )
            assert (
                client.post(
                    "/api/control/preferences", json={"title": "T", "content": "C"}
                ).status_code
                == 200
            )
    finally:
        app.dependency_overrides.clear()


def test_repeated_native_call_in_one_request_is_deduplicated(tmp_path, monkeypatch):
    store, db = state(tmp_path)
    store.install(manifest())
    call = {
        "message": {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "skill_test_skill", "arguments": {"count": 1}}}
            ],
        }
    }
    replies = iter(
        [
            call,
            call,
            {"message": {"role": "assistant", "content": "Queued for review."}},
        ]
    )

    async def fake(self, messages, tools):
        return next(replies)

    monkeypatch.setattr(OllamaProvider, "native_chat", fake)
    asyncio.run(
        Agent(Settings(), store, db, Scheduler(store, Settings())).chat(
            "Run", request_id="same-request"
        )
    )
    assert len(store.jobs()) == 1


def test_owner_password_accepts_pbkdf2_without_breaking_existing_hashes():
    from core.auth import verify_admin_password

    salt = bytes.fromhex("ab" * 16)
    digest = hashlib.pbkdf2_hmac("sha256", b"correct-password", salt, 100000).hex()
    settings = Settings(admin_password_hash=f"pbkdf2:100000:{salt.hex()}:{digest}")
    assert verify_admin_password("correct-password", settings)
    assert not verify_admin_password("wrong-password", settings)


def test_priority_tool_updates_existing_job_without_duplication(tmp_path):
    store, db = state(tmp_path)
    job = store.enqueue("Render", "test_skill", {"count": 1}, priority=5)
    agent = Agent(Settings(), store, db, Scheduler(store, Settings()))
    agent.dispatch("jobs_priority", {"job_id": job["id"], "priority": 1}, "request")
    assert len(store.jobs()) == 1
    assert store.job(job["id"])["priority"] == 1


def test_scheduler_completes_validated_command_and_schedules_recurrence(
    tmp_path, monkeypatch
):
    store, _ = state(tmp_path)
    m = manifest(
        transport="command",
        command=[sys.executable, "-c", "import json; print(json.dumps(dict(ok=True)))"],
    )
    store.install(m)
    job = store.enqueue(
        "Real command", "test_skill", {"count": 1}, approved=True, interval_seconds=60
    )
    scheduler = Scheduler(store, Settings())
    monkeypatch.setattr("control.scheduler.send_pending", lambda s: None)

    async def run():
        await scheduler.tick()
        await scheduler.worker

    asyncio.run(run())
    assert store.job(job["id"])["status"] == "completed"
    assert len(store.jobs()) == 2
    queued = [j for j in store.jobs() if j["status"] == "queued"]
    assert len(queued) == 1
    assert queued[0]["request_id"] != job["request_id"]


def test_bundlebee_adapter_reads_real_catalogue_shape_without_clicks(monkeypatch):
    from adapters import bundlebee

    monkeypatch.setenv("BUNDLEBEE_API_BASE", "https://bundlebee.example/api")
    monkeypatch.setattr(bundlebee, "public_url", lambda url: url.startswith("https://"))

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "items": [
                    {
                        "_id": "p1",
                        "name": "Test",
                        "productUrl": "https://retailer.example/product",
                        "affiliateUrl": "https://tracker.example/affiliate",
                    }
                ]
            }

    class Session:
        def get(self, url, **kwargs):
            assert url == "https://bundlebee.example/api/products"
            return Response()

        def head(self, url, **kwargs):
            assert url == "https://retailer.example/product"
            assert kwargs["allow_redirects"] is False
            return Response()

    monkeypatch.setattr(bundlebee.requests, "Session", Session)
    result = bundlebee.run(
        {"args": {"task": "link_validation", "max_items": 1, "dry_run": True}}
    )
    assert result["changes_applied"] is False
    assert result["findings"][0]["price_verified"] is False
    assert result["findings"][0]["status"] == "reachable"


def test_clock_facts_use_london_weekday_and_midnight():
    from datetime import datetime, timezone
    from control.agent import clock_facts, direct_clock_reply
    monday = clock_facts(datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc))
    assert monday["weekday"] == "Monday"
    assert direct_clock_reply("what day is today?", monday) == "Today is Monday, 12 October 2026 (Europe/London)."
    tuesday = clock_facts(datetime(2026, 10, 12, 23, 30, tzinfo=timezone.utc))
    assert tuesday["weekday"] == "Tuesday"
    assert tuesday["date"] == "13 October 2026"
    assert direct_clock_reply("Render today's match", monday) is None


def test_clock_answer_bypasses_model_and_remains_in_conversation(tmp_path, monkeypatch):
    from control import agent as agent_module
    store, db = state(tmp_path)
    scheduler = Scheduler(store, Settings())
    monkeypatch.setattr(agent_module, "clock_facts", lambda: {
        "weekday": "Monday", "date": "12 October 2026", "time": "23:00", "timezone": "Europe/London"})
    async def forbidden(*args, **kwargs):
        raise AssertionError("Clock answer must not use model inference")
    monkeypatch.setattr(OllamaProvider, "native_chat", forbidden)
    result = asyncio.run(Agent(Settings(), store, db, scheduler).chat("what day is today?", "clock-test"))
    assert result["model"] == "computer-clock"
    assert "Monday" in result["message"]
    history = db.get_recent_messages("clock-test", limit=16)
    assert history[-1]["content"] == result["message"]
