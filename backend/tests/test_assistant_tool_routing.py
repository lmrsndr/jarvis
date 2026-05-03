from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.assistant import Assistant
from core.config import Settings
from core.pending_actions import clear_all_pending_actions, get_pending_action, store_pending_action
from core.providers import ProviderResponse
from core.tool_router import route_tool_request
from memory.db import MemoryDatabase


class FakeLoader:
    def list_plugins(self) -> list[dict]:
        return [
            {"tool_name": "filesystem_manager", "enabled": True},
            {"tool_name": "web_search", "enabled": True},
        ]


class FakeProvider:
    called = False
    last_message = ""
    response_content = "model response"
    name = "ollama"
    model = "fake"
    external = False

    async def chat(self, message: str, history: list[dict[str, str]] | None = None) -> ProviderResponse:
        FakeProvider.called = True
        FakeProvider.last_message = message
        return ProviderResponse(content=FakeProvider.response_content, provider="ollama", model="fake")


class FakeRunner:
    calls: list[tuple[str, dict, bool]] = []

    def __init__(self, loader=None, settings=None) -> None:
        pass

    def run(self, name: str, args: dict, *, confirmed: bool = False, admin_password: str | None = None) -> dict:
        FakeRunner.calls.append((name, args, confirmed))
        action = args["action"]
        if action == "tree":
            result = {"path": args["path"], "tree": "Jarvis\n├── backend\n└── README.md"}
        elif action == "create_file":
            result = {"created": args["path"], "bytes": len(args.get("content", ""))}
        elif action == "delete":
            result = {"deleted": "/home/s-ndrlm-r/Projects/Jarvis/Jarvis.txt", "backup": None}
        else:
            result = {"ok": True}
        return {"tool_name": name, "result": result, "executed": True}


class FakeWebSearch:
    calls: list[dict] = []
    result: dict = {}

    @classmethod
    def run(cls, args: dict) -> dict:
        cls.calls.append(args)
        if cls.result:
            return cls.result
        return {
            "ok": True,
            "mode": "direct_api",
            "answer": f"live answer for {args['query']}",
            "confidence": 0.9,
            "sources": [{"title": "Source", "url": "https://example.com"}],
        }


@pytest.fixture(autouse=True)
def clear_pending_actions() -> None:
    clear_all_pending_actions()


def test_tree_chat_routes_to_filesystem_without_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)

    response = asyncio.run(
        assistant.chat("Can you give me a tree diagram of the Jarvis project in my Home/Projects folder?")
    )

    assert response.metadata["tool_used"] == "filesystem_manager"
    assert response.metadata["tool_action"] == "tree"
    assert response.metadata["tool_args"]["path"] == "~/Projects/Jarvis"
    assert response.metadata["executed"] is True
    assert response.metadata["model_used_after_tool"] is False
    assert FakeProvider.called is False
    assert FakeRunner.calls[0][1]["action"] == "tree"


def test_create_txt_file_routes_to_filesystem_without_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)

    response = asyncio.run(assistant.chat("create a txt file named Jarvis in my Home/Project folder"))

    assert response.metadata["tool_used"] == "filesystem_manager"
    assert response.metadata["tool_action"] == "create_file"
    assert response.metadata["tool_args"]["path"] == "~/Projects/Jarvis.txt"
    assert response.metadata["executed"] is True
    assert FakeProvider.called is False
    assert FakeRunner.calls[0][2] is True


def test_delete_requires_confirmation_without_provider_or_plugin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)

    response = asyncio.run(assistant.chat("Can you delete Jarvis.txt for me?"))

    assert response.metadata["tool_used"] == "filesystem_manager"
    assert response.metadata["tool_action"] == "delete"
    assert response.metadata["requires_confirmation"] is True
    assert response.metadata["executed"] is False
    assert response.metadata["pending_action_created"] is True
    assert "APPROVE DELETE" in response.message
    assert get_pending_action(response.conversation_id) is not None
    assert FakeProvider.called is False
    assert FakeRunner.calls == []


def test_exact_delete_approval_executes_pending_action(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    first = asyncio.run(assistant.chat("delete Jarvis.txt"))
    approval = first.metadata["approval_phrase"]

    response = asyncio.run(assistant.chat(approval, conversation_id=first.conversation_id))

    assert response.metadata["tool_used"] == "filesystem_manager"
    assert response.metadata["tool_action"] == "delete"
    assert response.metadata["requires_confirmation"] is False
    assert response.metadata["executed"] is True
    assert response.metadata["approval_accepted"] is True
    assert "Deleted /home/s-ndrlm-r/Projects/Jarvis/Jarvis.txt" in response.message
    assert get_pending_action(first.conversation_id) is None
    assert FakeProvider.called is False
    assert len(FakeRunner.calls) == 1
    tool_name, args, confirmed = FakeRunner.calls[0]
    assert tool_name == "filesystem_manager"
    assert args["action"] == "delete"
    assert args["admin_confirmed"] is True
    assert args["approval_text"] == approval
    assert confirmed is True


def test_approval_without_pending_action_does_not_execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)

    response = asyncio.run(
        assistant.chat("APPROVE DELETE: /home/s-ndrlm-r/Projects/Jarvis/Jarvis.txt")
    )

    assert "no pending protected action" in response.message
    assert response.metadata["executed"] is False
    assert response.metadata["approval_accepted"] is False
    assert FakeProvider.called is False
    assert FakeRunner.calls == []


def test_wrong_approval_phrase_does_not_execute_and_keeps_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    first = asyncio.run(assistant.chat("delete Jarvis.txt"))

    response = asyncio.run(
        assistant.chat(
            "APPROVE DELETE: /home/s-ndrlm-r/Projects/Jarvis/Wrong.txt",
            conversation_id=first.conversation_id,
        )
    )

    assert "does not match" in response.message
    assert response.metadata["executed"] is False
    assert response.metadata["approval_accepted"] is False
    assert get_pending_action(first.conversation_id) is not None
    assert FakeProvider.called is False
    assert FakeRunner.calls == []


def test_expired_approval_clears_pending_without_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    conversation_id = "expired-conversation"
    route = route_tool_request("delete Jarvis.txt", [{"tool_name": "filesystem_manager", "enabled": True}])
    store_pending_action(
        conversation_id,
        route,
        now=datetime.now(timezone.utc) - timedelta(minutes=6),
    )
    approval = route["approval_phrase"]

    response = asyncio.run(assistant.chat(approval, conversation_id=conversation_id))

    assert "approval request has expired" in response.message
    assert response.metadata["executed"] is False
    assert response.metadata["approval_accepted"] is False
    assert get_pending_action(conversation_id) is None
    assert FakeProvider.called is False
    assert FakeRunner.calls == []


def test_approval_in_different_conversation_does_not_execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    first = asyncio.run(assistant.chat("delete Jarvis.txt", conversation_id="conversation-a"))
    approval = first.metadata["approval_phrase"]

    response = asyncio.run(assistant.chat(approval, conversation_id="conversation-b"))

    assert "no pending protected action" in response.message
    assert get_pending_action("conversation-a") is not None
    assert response.metadata["executed"] is False
    assert FakeProvider.called is False
    assert FakeRunner.calls == []


def test_general_knowledge_can_use_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)

    response = asyncio.run(assistant.chat("What is DNS?"))

    assert response.message == "model response"
    assert FakeProvider.called is True
    assert FakeRunner.calls == []


def test_explicit_invention_can_use_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)

    response = asyncio.run(assistant.chat("Invent a possible folder structure for a new app"))

    assert response.message == "model response"
    assert FakeProvider.called is True
    assert FakeRunner.calls == []


def test_direct_api_live_query_returns_tool_answer_without_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    message = "weather in Bristol tomorrow"

    response = asyncio.run(assistant.chat(message))

    assert response.message == f"live answer for {message}"
    assert response.metadata["tool_used"] == "web_search"
    assert response.metadata["tool_args"]["query"] == message
    assert response.metadata["executed"] is True
    assert response.metadata["tool_result_ok"] is True
    assert response.metadata["model_used_after_tool"] is False
    assert response.metadata["mode"] == "direct_api"
    assert response.metadata["documents_count"] == 0
    assert response.metadata["ollama_grounded"] is False
    assert FakeProvider.called is False
    assert FakeWebSearch.calls == [{"query": message}]
    assert FakeRunner.calls == []


def test_trusted_rag_query_uses_grounded_ollama(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    FakeProvider.response_content = "Oil prices rose according to Reuters. [S1]"
    FakeWebSearch.result = {
        "ok": True,
        "mode": "trusted_rag",
        "query": "latest oil prices",
        "documents": [
            {
                "source_name": "Reuters",
                "url": "https://www.reuters.com/markets/commodities/oil",
                "title": "Oil rises",
                "published": "2026-05-03",
                "text": "Brent crude oil prices rose to $82 a barrel.",
                "tables": [],
                "relevance_score": 0.2,
            }
        ],
        "sources": [{"source_name": "Reuters", "url": "https://www.reuters.com/markets/commodities/oil"}],
        "confidence": 0.8,
    }

    response = asyncio.run(assistant.chat("latest oil prices"))

    assert response.message == "Oil prices rose according to Reuters. [S1]"
    assert response.provider == "ollama"
    assert response.metadata["tool_used"] == "web_search"
    assert response.metadata["mode"] == "trusted_rag"
    assert response.metadata["documents_count"] == 1
    assert response.metadata["ollama_grounded"] is True
    assert "Answer ONLY using provided text" in FakeProvider.last_message
    assert "Brent crude oil prices rose" in FakeProvider.last_message
    assert FakeWebSearch.calls == [{"query": "latest oil prices"}]


def test_trusted_rag_insufficient_data_starts_teaching_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    FakeProvider.response_content = "INSUFFICIENT_TRUSTED_DATA"
    FakeWebSearch.result = {
        "ok": True,
        "mode": "trusted_rag",
        "query": "latest oil prices",
        "category": "finance_energy",
        "documents": [
            {
                "source_name": "Reuters",
                "url": "https://www.reuters.com/markets/commodities/oil",
                "title": "Oil rises",
                "published": "2026-05-03",
                "text": "A short oil market update.",
                "tables": [],
                "relevance_score": 0.2,
            }
        ],
        "sources": [{"source_name": "Reuters", "url": "https://www.reuters.com/markets/commodities/oil"}],
        "confidence": 0.8,
    }

    response = asyncio.run(assistant.chat("latest oil prices", conversation_id="insufficient-a"))

    assert response.message.startswith("I do not have trusted sources for this topic yet.")
    assert response.metadata["learning_mode"] == "awaiting_sources"
    assert response.metadata["ollama_grounded"] is True
    assert FakeProvider.called is True


def test_web_search_failure_returns_strict_unverified_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    FakeWebSearch.result = {"ok": False, "error": "offline", "answer": "Search failed.", "confidence": 0.0}

    response = asyncio.run(assistant.chat("current football scores"))

    assert response.message == "I could not verify this from trusted sources."
    assert FakeProvider.called is False
    assert FakeWebSearch.calls == [{"query": "current football scores"}]
    assert FakeRunner.calls == []


def test_unknown_live_topic_asks_for_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    FakeWebSearch.result = {
        "ok": True,
        "mode": "needs_sources",
        "answer": "I do not have trusted sources for this topic yet. Please provide 2-5 reliable sources (URLs) so I can learn.",
        "confidence": 0.0,
        "teach_request": True,
        "suggested_action": {
            "action": "add_source_category",
            "category": "latest_quantum_chip_news",
            "keywords": ["latest", "quantum", "chip", "news"],
        },
    }

    response = asyncio.run(assistant.chat("latest quantum chip news", conversation_id="learn-a"))

    assert response.message.startswith("I do not have trusted sources for this topic yet.")
    assert response.metadata["learning_mode"] == "awaiting_sources"
    assert response.metadata["suggested_category"] == "latest_quantum_chip_news"
    assert FakeProvider.called is False


def test_learning_sources_are_confirmed_and_saved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)
    FakeWebSearch.result = {
        "ok": True,
        "mode": "needs_sources",
        "answer": "I do not have trusted sources for this topic yet. Please provide 2-5 reliable sources (URLs) so I can learn.",
        "confidence": 0.0,
        "teach_request": True,
    }
    first = asyncio.run(assistant.chat("latest quantum chip news", conversation_id="learn-b"))

    sources = asyncio.run(
        assistant.chat(
            "https://example.com/quantum https://example.org/chips",
            conversation_id=first.conversation_id,
        )
    )

    assert "Type CONFIRM to proceed." in sources.message
    assert "Category name: quantum_chip_news" in sources.message

    FakeWebSearch.result = {"ok": True, "answer": "Added trusted source category.", "confidence": 1.0}
    saved = asyncio.run(assistant.chat("CONFIRM", conversation_id=first.conversation_id))

    assert saved.message == "Sources saved. I will use these for future queries."
    assert FakeWebSearch.calls[-1] == {
        "action": "add_source_category",
        "category": "quantum_chip_news",
        "description": "User-defined trusted sources",
        "sources": ["https://example.com/quantum", "https://example.org/chips"],
        "keywords": ["quantum", "chip", "news"],
    }
    assert FakeProvider.called is False


def test_path_escape_is_blocked_without_provider_or_plugin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assistant = _assistant(tmp_path)
    _patch_chat_dependencies(monkeypatch)

    response = asyncio.run(assistant.chat("Delete ../../.ssh/id_rsa"))

    assert response.metadata["tool_used"] == "filesystem_manager"
    assert response.metadata["tool_action"] == "delete"
    assert response.metadata["executed"] is False
    assert "outside ~/Projects" in response.message
    assert FakeProvider.called is False
    assert FakeRunner.calls == []


def _assistant(tmp_path: Path) -> Assistant:
    settings = Settings(
        memory_db_path=str(tmp_path / "memory.db"),
        vector_path=str(tmp_path / "vectors.json"),
    )
    memory_db = MemoryDatabase(settings.memory_db_path)
    memory_db.init()
    return Assistant(settings, memory_db)


def _patch_chat_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeProvider.called = False
    FakeProvider.last_message = ""
    FakeProvider.response_content = "model response"
    FakeRunner.calls = []
    FakeWebSearch.calls = []
    FakeWebSearch.result = {}
    monkeypatch.setattr("core.assistant.PluginLoader", FakeLoader)
    monkeypatch.setattr("core.assistant.PluginRunner", FakeRunner)
    monkeypatch.setattr("core.assistant.web_search_run", FakeWebSearch.run)
    monkeypatch.setattr("core.assistant.get_provider", lambda *args, **kwargs: FakeProvider())
