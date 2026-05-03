from __future__ import annotations

import os
import sys
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ["JARVIS_MEMORY_DB_PATH"] = str(BACKEND_DIR / "tests" / "test_memory.db")
os.environ["JARVIS_VECTOR_PATH"] = str(BACKEND_DIR / "tests" / "test_vectors.json")
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["JARVIS_ADMIN_PASSWORD_HASH"] = hashlib.sha256("delete-test".encode("utf-8")).hexdigest()

from main import app  # noqa: E402


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_provider_status_defaults_to_ollama() -> None:
    response = client.get("/api/system/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert providers[0]["name"] == "local"
    assert providers[0]["provider"] == "ollama"
    assert providers[0]["default"] is True
    assert all(provider["default"] is False for provider in providers[1:])


def test_provider_switching_requires_key_for_external_providers() -> None:
    local_response = client.post("/api/system/provider", json={"provider": "local"})
    assert local_response.status_code == 200
    assert local_response.json()["selected_provider"] == "ollama"

    openai_response = client.post("/api/system/provider", json={"provider": "openai"})
    assert openai_response.status_code == 400
    assert "API key" in openai_response.json()["detail"]


def test_login_session_and_provider_key_test_admin_confirmation() -> None:
    failed_login = client.post("/api/system/login", json={"password": "wrong"})
    assert failed_login.status_code == 403

    login_response = client.post("/api/system/login", json={"password": "delete-test"})
    assert login_response.status_code == 200
    assert login_response.json()["authenticated"] is True

    session_response = client.get("/api/system/session")
    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True

    denied_key_test = client.post("/api/system/providers/openai/test", json={"admin_password": "wrong"})
    assert denied_key_test.status_code == 403

    key_test = client.post("/api/system/providers/openai/test", json={"admin_password": "delete-test"})
    assert key_test.status_code == 200
    assert key_test.json()["remote_call_performed"] is False


def test_echo_plugin() -> None:
    response = client.post("/api/plugins/echo_tool/run", json={"args": {"text": "hello"}})
    assert response.status_code == 200
    assert response.json()["result"]["text"] == "hello"


def test_memory_create_search_and_detail() -> None:
    create_response = client.post(
        "/api/memory",
        json={
            "memory_type": "project",
            "title": "Local memory project",
            "content": "Jarvis stores structured memory locally in SQLite.",
            "tags": ["local", "sqlite"],
            "source": "test",
            "confidence": 0.9,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["memory_type"] == "project"

    search_response = client.get("/api/memory/search", params={"q": "structured local memory"})
    assert search_response.status_code == 200
    assert any(item["id"] == created["id"] for item in search_response.json()["memories"])

    detail_response = client.get(f"/api/memory/{created['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["title"] == "Local memory project"


def test_memory_delete_requires_admin_password() -> None:
    create_response = client.post(
        "/api/memory",
        json={
            "memory_type": "fact",
            "title": "Delete protection",
            "content": "This memory should require admin confirmation to delete.",
        },
    )
    memory_id = create_response.json()["id"]

    missing_password = client.request("DELETE", f"/api/memory/{memory_id}", json={})
    assert missing_password.status_code == 422

    wrong_password = client.request("DELETE", f"/api/memory/{memory_id}", json={"admin_password": "wrong"})
    assert wrong_password.status_code == 403

    correct_password = client.request("DELETE", f"/api/memory/{memory_id}", json={"admin_password": "delete-test"})
    assert correct_password.status_code == 200
    assert correct_password.json()["deleted"] is True

    detail_response = client.get(f"/api/memory/{memory_id}")
    assert detail_response.status_code == 404


def test_voice_transcribe_endpoint_returns_clear_local_stt_error() -> None:
    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("voice.webm", b"not real audio", "audio/webm")},
    )
    assert response.status_code == 400
    assert "Local speech-to-text failed" in response.json()["detail"]
