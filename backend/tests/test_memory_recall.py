from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from core import assistant as assistant_module
from core.assistant import Assistant
from core.config import Settings
from core.providers import ProviderResponse
from memory.db import MemoryDatabase
from memory.recall import decide_memory_use, recall_context
from memory.vector_store import LocalVectorStore


class FakeProvider:
    name = "fake"
    model = "fake-model"
    external = False

    async def chat(self, message: str, history: list[dict[str, str]] | None = None) -> ProviderResponse:
        return ProviderResponse(content="ok", provider=self.name, model=self.model, external=self.external)


class SearchExplodingVectorStore:
    def __init__(self, path: str) -> None:
        self.path = path

    def search(self, query: str, limit: int = 5) -> list[dict]:
        raise AssertionError("memory search should not run for general knowledge requests")

    def add(self, document_id: str, text: str, metadata: dict | None = None) -> None:
        return None


def test_general_knowledge_question_does_not_use_memory(tmp_path, monkeypatch) -> None:
    settings = Settings(
        memory_db_path=str(tmp_path / "memory.db"),
        vector_path=str(tmp_path / "vectors.json"),
    )
    memory_db = MemoryDatabase(settings.memory_db_path)
    memory_db.init()

    decision = decide_memory_use("What is DNS?")
    assert decision.use_memory is False
    assert decision.allowed_memory_types == []

    monkeypatch.setattr(assistant_module, "get_provider", lambda *args, **kwargs: FakeProvider())
    monkeypatch.setattr(assistant_module, "LocalVectorStore", SearchExplodingVectorStore)

    response = asyncio.run(Assistant(settings, memory_db).chat("What is DNS?"))
    assert response.recalled == []


def test_identity_question_uses_identity_memory(tmp_path) -> None:
    memory_db, vector_store = _memory_stack(tmp_path)
    _create_indexed_memory(
        memory_db,
        vector_store,
        memory_type="fact",
        title="User name",
        content="The user's name is Elem.",
        tags=["identity"],
    )

    decision = decide_memory_use("What is my name?")
    recalled = recall_context(
        memory_db,
        vector_store,
        "What is my name?",
        allowed_memory_types=decision.allowed_memory_types,
        allow_identity=decision.allow_identity,
    )

    assert decision.use_memory is True
    assert decision.allow_identity is True
    assert [item["title"] for item in recalled] == ["User name"]


def test_project_question_uses_project_technical_memory(tmp_path) -> None:
    memory_db, vector_store = _memory_stack(tmp_path)
    _create_indexed_memory(
        memory_db,
        vector_store,
        memory_type="project",
        title="Jarvis backend configuration",
        content="Jarvis backend is configured with FastAPI, SQLite memory, and a local vector store.",
        tags=["jarvis", "backend", "configuration"],
    )
    _create_indexed_memory(
        memory_db,
        vector_store,
        memory_type="fact",
        title="User name",
        content="The user's name is Elem.",
        tags=["identity"],
    )

    decision = decide_memory_use("How did we configure Jarvis backend?")
    recalled = recall_context(
        memory_db,
        vector_store,
        "How did we configure Jarvis backend?",
        allowed_memory_types=decision.allowed_memory_types,
        allow_identity=decision.allow_identity,
    )

    assert decision.use_memory is True
    assert any(item["memory_type"] == "project" for item in recalled)
    assert all(item["title"] != "User name" for item in recalled)


def test_continue_from_last_time_uses_conversation_project_memory(tmp_path) -> None:
    memory_db, vector_store = _memory_stack(tmp_path)
    _create_indexed_memory(
        memory_db,
        vector_store,
        memory_type="conversation_summary",
        title="Continue from last time",
        content="Last time we configured Jarvis backend memory gating for project recall.",
        tags=["conversation", "project", "jarvis"],
    )

    decision = decide_memory_use("Continue from last time")
    recalled = recall_context(
        memory_db,
        vector_store,
        "Continue from last time",
        allowed_memory_types=decision.allowed_memory_types,
        allow_identity=decision.allow_identity,
    )

    assert decision.use_memory is True
    assert [item["memory_type"] for item in recalled] == ["conversation_summary"]


def _memory_stack(tmp_path) -> tuple[MemoryDatabase, LocalVectorStore]:
    memory_db = MemoryDatabase(str(tmp_path / "memory.db"))
    memory_db.init()
    vector_store = LocalVectorStore(str(tmp_path / "vectors.json"))
    return memory_db, vector_store


def _create_indexed_memory(
    memory_db: MemoryDatabase,
    vector_store: LocalVectorStore,
    memory_type: str,
    title: str,
    content: str,
    tags: list[str],
) -> None:
    memory = memory_db.create_memory(
        memory_type=memory_type,
        title=title,
        content=content,
        tags=tags,
        source="test",
        confidence=1.0,
    )
    vector_store.add(
        str(memory["id"]),
        f"{memory['title']}\n{memory['content']}\n{' '.join(memory['tags'])}",
        {
            "memory_type": memory["memory_type"],
            "title": memory["title"],
            "source": memory["source"],
        },
    )
