from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.audit_log import write_audit_event
from core.config import Settings
from core.pending_actions import (
    PendingProtectedAction,
    clear_pending_action,
    get_pending_action,
    is_approval_message,
    store_pending_action,
)
from core.providers import EXTERNAL_PROVIDERS, get_provider, get_selected_provider, normalize_provider_name
from core.tool_router import route_tool_request
from memory.db import MemoryDatabase
from memory.recall import DEFAULT_RECALL_LIMIT, decide_memory_use, recall_context
from memory.vector_store import LocalVectorStore
from plugins.loader import PluginLoader, PluginNotFoundError, PluginValidationError
from plugins.runner import PluginPermissionError, PluginRunner


MEMORY_SYSTEM_POLICY = (
    "You have access to local memory, but you must not mention or use stored memories unless they are directly "
    "relevant to the user's current request. First decide whether the question can be answered from general "
    "knowledge alone. Use memory only when it improves correctness or continuity. Do not say 'I remember' unless "
    "the user asks about memory. Do not include personal facts unless naturally needed."
)
TOOL_SYSTEM_POLICY = (
    "Never invent local filesystem contents, file operations, command output, logs, search results, current/live "
    "information, or project structure. If the user asks for something requiring a tool, use an enabled tool if "
    "available. If no suitable tool exists, say the capability is unavailable. Do not provide hypothetical shell "
    "commands unless the user explicitly asks for a command or tutorial."
)
logger = logging.getLogger(__name__)
TRUSTED_SOURCE_PROMPT = (
    "I do not have trusted sources for this topic yet.\n"
    "Please provide 2-5 reliable sources (URLs) so I can learn."
)
UNVERIFIED_RESPONSE = "I could not verify this from trusted sources."
LOW_CONFIDENCE_THRESHOLD = 0.55
CURRENT_INFO_KEYWORDS = (
    "weather",
    "forecast",
    "temperature",
    "rain",
    "wind",
    "today",
    "tomorrow",
    "latest",
    "current",
    "news",
    "score",
    "scores",
    "result",
    "results",
    "fixture",
    "fixtures",
    "calendar",
    "match",
    "next match",
    "premier league",
    "football",
    "chelsea",
    "arsenal",
    "man utd",
)
_LEARNING_STATES: dict[str, dict[str, Any]] = {}


@dataclass
class AssistantResponse:
    conversation_id: str
    provider: str
    message: str
    recalled: list[dict[str, str]]
    metadata: dict[str, Any]


class Assistant:
    def __init__(self, settings: Settings, memory_db: MemoryDatabase) -> None:
        self.settings = settings
        self.memory_db = memory_db

    async def chat(self, message: str, provider_name: str | None = None, conversation_id: str | None = None) -> AssistantResponse:
        selected_provider = normalize_provider_name(provider_name or get_selected_provider())
        active_conversation_id = conversation_id or str(uuid4())
        plugin_loader = PluginLoader()
        if is_approval_message(message):
            return self._chat_with_protected_action_approval(
                message=message,
                selected_provider=selected_provider,
                conversation_id=active_conversation_id,
                plugin_loader=plugin_loader,
            )

        learning_response = self._chat_with_learning_state(
            message=message,
            selected_provider=selected_provider,
            conversation_id=active_conversation_id,
        )
        if learning_response is not None:
            return learning_response

        history = self.memory_db.get_recent_messages(active_conversation_id, limit=12)
        plugins = plugin_loader.list_plugins()
        route = route_tool_request(message, plugins, context={"recent_messages": history})
        classification = _classify_current_info_query(message)
        logger.info("query classification", extra={"classification": classification})
        write_audit_event(
            "chat.query_classification",
            {
                "conversation_id": active_conversation_id,
                "provider": selected_provider,
                **classification,
            },
        )
        if route.get("needs_clarification"):
            return self._chat_with_clarification(
                message=message,
                selected_provider=selected_provider,
                conversation_id=active_conversation_id,
                route=route,
            )
        if classification["current_info"]:
            web_response = await self._chat_with_web_search(
                message=message,
                selected_provider=selected_provider,
                conversation_id=active_conversation_id,
                route=_web_search_route(message, classification["matched_keywords"]),
            )
            if web_response is not None:
                return web_response

        if route["use_tool"]:
            if route.get("tool_name") == "web_search":
                web_response = await self._chat_with_web_search(
                    message=message,
                    selected_provider=selected_provider,
                    conversation_id=active_conversation_id,
                    route=route,
                    plugin_loader=plugin_loader,
                )
                if web_response is not None:
                    return web_response
                logger.info("web_search skipped")
            else:
                logger.info("web_search skipped")
                return self._chat_with_tool(
                    message=message,
                    selected_provider=selected_provider,
                    conversation_id=active_conversation_id,
                    route=route,
                    plugin_loader=plugin_loader,
                )
        if route["requires_tool"]:
            logger.info("web_search skipped")
            return self._chat_without_required_tool(
                message=message,
                selected_provider=selected_provider,
                conversation_id=active_conversation_id,
                route=route,
            )
        logger.info("web_search skipped")

        explicit = provider_name is not None or selected_provider in EXTERNAL_PROVIDERS
        provider = get_provider(selected_provider, self.settings, explicit=explicit)

        vector_store = LocalVectorStore(self.settings.vector_path)
        memory_decision = decide_memory_use(message)
        recalled = (
            recall_context(
                self.memory_db,
                vector_store,
                message,
                limit=DEFAULT_RECALL_LIMIT,
                allowed_memory_types=memory_decision.allowed_memory_types,
                allow_identity=memory_decision.allow_identity,
            )
            if memory_decision.use_memory
            else []
        )
        context_prefix = _build_context_prefix(recalled)
        prompt = _build_prompt(message, context_prefix)

        self.memory_db.add_message(active_conversation_id, "user", message, selected_provider)
        provider_response = await provider.chat(prompt, history=history)
        reply = provider_response.content
        self.memory_db.add_message(active_conversation_id, "assistant", reply, selected_provider)
        self._save_conversation_summary(active_conversation_id, message, reply, selected_provider, vector_store)
        write_audit_event(
            "chat",
            {"conversation_id": active_conversation_id, "provider": selected_provider, "message_length": len(message)},
        )
        return AssistantResponse(active_conversation_id, selected_provider, reply, recalled, provider_response.metadata)

    def _chat_with_tool(
        self,
        message: str,
        selected_provider: str,
        conversation_id: str,
        route: dict[str, Any],
        plugin_loader: PluginLoader,
    ) -> AssistantResponse:
        tool_name = str(route["tool_name"])
        args = dict(route.get("args") or {})
        self.memory_db.add_message(conversation_id, "user", message, selected_provider)
        if route.get("requires_confirmation"):
            pending = store_pending_action(conversation_id, route)
            reply = _confirmation_message(route)
            self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
            metadata = _tool_metadata(
                selected_provider=selected_provider,
                route=route,
                executed=False,
                tool_result_ok=False,
            )
            metadata["pending_action_created"] = True
            metadata["pending_action_expires_at"] = pending.expires_at.isoformat()
            write_audit_event(
                "chat.pending_action.created",
                {
                    **_tool_audit_payload(conversation_id, selected_provider, route, executed=False),
                    "approval_phrase": pending.approval_phrase,
                    "expires_at": pending.expires_at.isoformat(),
                },
            )
            return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

        executed = False
        try:
            confirmed = _chat_may_confirm_tool_run(tool_name, args)
            run_result = PluginRunner(loader=plugin_loader, settings=self.settings).run(
                tool_name,
                args,
                confirmed=confirmed,
            )
            executed = bool(run_result.get("executed"))
            tool_result = run_result["result"]
            reply = _answer_from_tool_result(tool_name, tool_result)
        except (PluginNotFoundError, PluginValidationError, PluginPermissionError) as exc:
            tool_result = {"error": str(exc)}
            reply = _tool_error_message(tool_name, str(exc))

        self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
        metadata = _tool_metadata(
            selected_provider=selected_provider,
            route=route,
            executed=executed,
            tool_result_ok="error" not in tool_result and tool_result.get("ok", True) is not False,
        )
        write_audit_event(
            "chat.tool_route",
            _tool_audit_payload(conversation_id, selected_provider, route, executed=executed),
        )
        return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

    def _chat_with_clarification(
        self,
        message: str,
        selected_provider: str,
        conversation_id: str,
        route: dict[str, Any],
    ) -> AssistantResponse:
        reply = str(route.get("clarification") or "I need one more detail before I can run that tool.")
        self.memory_db.add_message(conversation_id, "user", message, selected_provider)
        self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
        metadata = {
            "provider": selected_provider,
            "tool_used": route.get("tool_name"),
            "tool_reason": route.get("reason"),
            "missing_fields": route.get("missing_fields") or [],
            "requires_confirmation": False,
            "executed": False,
            "model_used_after_tool": False,
        }
        write_audit_event(
            "chat.plugin_clarification",
            {
                "conversation_id": conversation_id,
                "provider": selected_provider,
                "tool_name": route.get("tool_name"),
                "missing_fields": route.get("missing_fields") or [],
                "reason": route.get("reason"),
            },
        )
        return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

    async def _chat_with_web_search(
        self,
        message: str,
        selected_provider: str,
        conversation_id: str,
        route: dict[str, Any],
        plugin_loader: PluginLoader | None = None,
    ) -> AssistantResponse | None:
        logger.info("web_search triggered")
        try:
            run_result = PluginRunner(loader=plugin_loader or PluginLoader(), settings=self.settings).run(
                "web_search",
                {"action": "search", "query": message},
            )
            tool_result = run_result["result"]
            executed = True
        except (PluginNotFoundError, PluginValidationError, PluginPermissionError) as exc:
            tool_result = {"ok": False, "error": str(exc)}
            executed = False

        mode = str(tool_result.get("mode") or "")
        documents = list(tool_result.get("documents") or [])
        confidence = _tool_confidence(tool_result)
        tool_result_ok = (
            "error" not in tool_result
            and tool_result.get("ok", True) is not False
            and mode in {"direct_api", "trusted_rag"}
            and (mode != "trusted_rag" or bool(documents))
        )
        metadata = _tool_metadata(
            selected_provider=selected_provider,
            route=route,
            executed=executed,
            tool_result_ok=tool_result_ok,
        )
        metadata.update(
            {
                "mode": mode,
                "sources": tool_result.get("sources") or [],
                "documents_count": len(documents),
                "ollama_grounded": False,
            }
        )
        write_audit_event(
            "chat.tool_route",
            _tool_audit_payload(conversation_id, selected_provider, route, executed=executed),
        )

        if tool_result_ok and mode == "direct_api":
            reply = _answer_from_tool_result("web_search", tool_result)
            logger.info("tool result used")
            self.memory_db.add_message(conversation_id, "user", message, selected_provider)
            self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
            return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

        if tool_result_ok and mode == "trusted_rag" and documents:
            prompt = _build_trusted_rag_prompt(message, documents)
            ollama = get_provider("ollama", self.settings, explicit=False)
            provider_response = await ollama.chat(prompt, history=[])
            reply = provider_response.content.strip()
            metadata.update(provider_response.metadata)
            metadata["ollama_grounded"] = True
            metadata["model_used_after_tool"] = True
            if reply == "INSUFFICIENT_TRUSTED_DATA":
                insufficient_result = {
                    **tool_result,
                    "teach_request": True,
                    "suggested_action": {
                        "action": "add_source_category",
                        "category": tool_result.get("category") or _generate_category_name(message),
                        "keywords": _extract_keywords(message),
                    },
                }
                return self._start_learning_mode(message, selected_provider, conversation_id, route, insufficient_result, metadata)
            logger.info("trusted_rag answer used")
            self.memory_db.add_message(conversation_id, "user", message, "ollama")
            self.memory_db.add_message(conversation_id, "assistant", reply, "ollama")
            write_audit_event(
                "chat.trusted_rag.answered",
                {
                    "conversation_id": conversation_id,
                    "provider": "ollama",
                    "documents_count": len(documents),
                    "sources": metadata["sources"],
                },
            )
            return AssistantResponse(conversation_id, "ollama", reply, [], metadata)

        logger.info(
            "fallback triggered",
            extra={"tool_ok": tool_result.get("ok"), "confidence": confidence, "teach_request": bool(tool_result.get("teach_request"))},
        )
        write_audit_event(
            "chat.web_search.fallback",
            {
                "conversation_id": conversation_id,
                "provider": selected_provider,
                "tool_ok": bool(tool_result.get("ok")),
                "confidence": confidence,
                "teach_request": bool(tool_result.get("teach_request")),
            },
        )
        if _should_start_learning(tool_result):
            return self._start_learning_mode(message, selected_provider, conversation_id, route, tool_result, metadata)

        reply = UNVERIFIED_RESPONSE
        self.memory_db.add_message(conversation_id, "user", message, selected_provider)
        self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
        return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

    def _start_learning_mode(
        self,
        message: str,
        selected_provider: str,
        conversation_id: str,
        route: dict[str, Any],
        tool_result: dict[str, Any],
        metadata: dict[str, Any],
    ) -> AssistantResponse:
        suggested = dict(tool_result.get("suggested_action") or {})
        category = _generate_category_name(message, str(suggested.get("category") or ""))
        keywords = _extract_keywords(message)
        if suggested_keywords := suggested.get("keywords"):
            keywords = _dedupe([*keywords, *(str(item).strip().lower() for item in suggested_keywords)])
        _LEARNING_STATES[conversation_id] = {
            "stage": "awaiting_sources",
            "query": message,
            "category": category,
            "keywords": keywords,
            "route": route,
        }
        logger.info("learning mode triggered", extra={"category": category})
        write_audit_event(
            "chat.learning_mode.triggered",
            {"conversation_id": conversation_id, "provider": selected_provider, "category": category, "keywords": keywords},
        )
        metadata["learning_mode"] = "awaiting_sources"
        metadata["suggested_category"] = category
        self.memory_db.add_message(conversation_id, "user", message, selected_provider)
        self.memory_db.add_message(conversation_id, "assistant", TRUSTED_SOURCE_PROMPT, selected_provider)
        return AssistantResponse(conversation_id, selected_provider, TRUSTED_SOURCE_PROMPT, [], metadata)

    def _chat_with_learning_state(
        self,
        message: str,
        selected_provider: str,
        conversation_id: str,
    ) -> AssistantResponse | None:
        state = _LEARNING_STATES.get(conversation_id)
        if not state:
            return None

        self.memory_db.add_message(conversation_id, "user", message, selected_provider)
        if state["stage"] == "awaiting_sources":
            sources = _extract_urls(message)
            if len(sources) < 2 or len(sources) > 5:
                reply = "Please provide 2-5 reliable source URLs."
                self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
                return AssistantResponse(
                    conversation_id,
                    selected_provider,
                    reply,
                    [],
                    {"provider": selected_provider, "learning_mode": "awaiting_sources", "model_used_after_tool": False},
                )
            state["stage"] = "awaiting_confirmation"
            state["sources"] = sources
            reply = (
                "I will save these sources under a new category:\n"
                f"Category name: {state['category']}\n"
                "Sources:\n"
                + "\n".join(f"- {source}" for source in sources)
                + "\n\nType CONFIRM to proceed."
            )
            logger.info("learning mode sources received", extra={"category": state["category"], "source_count": len(sources)})
            write_audit_event(
                "chat.learning_mode.sources_received",
                {
                    "conversation_id": conversation_id,
                    "provider": selected_provider,
                    "category": state["category"],
                    "source_count": len(sources),
                },
            )
            self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
            return AssistantResponse(
                conversation_id,
                selected_provider,
                reply,
                [],
                {"provider": selected_provider, "learning_mode": "awaiting_confirmation", "category": state["category"], "sources": sources, "model_used_after_tool": False},
            )

        if state["stage"] == "awaiting_confirmation":
            if message.strip() != "CONFIRM":
                reply = "Source saving cancelled. Ask again when you want to teach trusted sources for this topic."
                _LEARNING_STATES.pop(conversation_id, None)
                self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
                return AssistantResponse(
                    conversation_id,
                    selected_provider,
                    reply,
                    [],
                    {"provider": selected_provider, "learning_mode": "cancelled", "model_used_after_tool": False},
                )
            run_result = PluginRunner(settings=self.settings).run(
                "web_search",
                {
                    "action": "add_source_category",
                    "category": state["category"],
                    "description": "User-defined trusted sources",
                    "sources": state["sources"],
                    "keywords": state["keywords"],
                },
                confirmed=True,
            )
            result = run_result["result"]
            _LEARNING_STATES.pop(conversation_id, None)
            if result.get("ok") is True:
                reply = "Sources saved. I will use these for future queries."
                saved = True
            else:
                reply = UNVERIFIED_RESPONSE
                saved = False
            logger.info("sources saved", extra={"category": state["category"], "saved": saved})
            write_audit_event(
                "chat.learning_mode.sources_saved",
                {
                    "conversation_id": conversation_id,
                    "provider": selected_provider,
                    "category": state["category"],
                    "saved": saved,
                    "source_count": len(state["sources"]),
                },
            )
            self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
            return AssistantResponse(
                conversation_id,
                selected_provider,
                reply,
                [],
                {"provider": selected_provider, "learning_mode": "saved" if saved else "save_failed", "category": state["category"], "tool_result": result, "model_used_after_tool": False},
            )

        _LEARNING_STATES.pop(conversation_id, None)
        return None

    def _chat_with_protected_action_approval(
        self,
        message: str,
        selected_provider: str,
        conversation_id: str,
        plugin_loader: PluginLoader,
    ) -> AssistantResponse:
        approval_text = message.strip()
        self.memory_db.add_message(conversation_id, "user", message, selected_provider)
        write_audit_event(
            "chat.pending_action.approval_received",
            {"conversation_id": conversation_id, "approval_prefix": approval_text.split(":", 1)[0]},
        )

        pending = get_pending_action(conversation_id)
        if pending is None:
            reply = "There is no pending protected action matching that approval."
            metadata = _approval_metadata(selected_provider, None, executed=False, accepted=False)
            self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
            write_audit_event(
                "chat.pending_action.missing",
                {"conversation_id": conversation_id, "executed": False},
            )
            return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

        if pending.is_expired():
            clear_pending_action(conversation_id)
            reply = "That approval request has expired. Please ask me to perform the action again."
            metadata = _approval_metadata(selected_provider, pending, executed=False, accepted=False)
            self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
            write_audit_event(
                "chat.pending_action.expired",
                {
                    "conversation_id": conversation_id,
                    "tool_name": pending.tool_name,
                    "action": pending.action,
                    "path": pending.args.get("path"),
                    "executed": False,
                },
            )
            write_audit_event(
                "chat.pending_action.cleared",
                {"conversation_id": conversation_id, "reason": "expired"},
            )
            return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

        if approval_text != pending.approval_phrase:
            reply = "Approval phrase does not match. Please copy it exactly."
            metadata = _approval_metadata(selected_provider, pending, executed=False, accepted=False)
            self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
            write_audit_event(
                "chat.pending_action.mismatch",
                {
                    "conversation_id": conversation_id,
                    "tool_name": pending.tool_name,
                    "action": pending.action,
                    "path": pending.args.get("path"),
                    "executed": False,
                },
            )
            return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

        write_audit_event(
            "chat.pending_action.matched",
            {
                "conversation_id": conversation_id,
                "tool_name": pending.tool_name,
                "action": pending.action,
                "path": pending.args.get("path"),
            },
        )
        args = dict(pending.args)
        args["admin_confirmed"] = True
        args["approval_text"] = approval_text
        executed = False
        try:
            run_result = PluginRunner(loader=plugin_loader, settings=self.settings).run(
                pending.tool_name,
                args,
                confirmed=True,
            )
            executed = bool(run_result.get("executed"))
            tool_result = run_result["result"]
            reply = _answer_from_tool_result(pending.tool_name, tool_result)
        except (PluginNotFoundError, PluginValidationError, PluginPermissionError) as exc:
            tool_result = {"error": str(exc)}
            reply = _tool_error_message(pending.tool_name, str(exc))
        finally:
            clear_pending_action(conversation_id)
            write_audit_event(
                "chat.pending_action.cleared",
                {"conversation_id": conversation_id, "reason": "executed_or_failed"},
            )

        metadata = _approval_metadata(
            selected_provider,
            pending,
            executed=executed,
            accepted=True,
            tool_result_ok="error" not in tool_result and tool_result.get("ok", True) is not False,
        )
        self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
        write_audit_event(
            "chat.pending_action.executed",
            {
                "conversation_id": conversation_id,
                "tool_name": pending.tool_name,
                "action": pending.action,
                "path": pending.args.get("path"),
                "confirmation_required": False,
                "executed": executed,
            },
        )
        return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

    def _chat_without_required_tool(
        self,
        message: str,
        selected_provider: str,
        conversation_id: str,
        route: dict[str, Any],
    ) -> AssistantResponse:
        missing_tool = route.get("missing_tool") or "suitable tool"
        reply = _blocked_tool_message(route) if route.get("blocked") else _missing_tool_message(str(missing_tool))
        self.memory_db.add_message(conversation_id, "user", message, selected_provider)
        self.memory_db.add_message(conversation_id, "assistant", reply, selected_provider)
        metadata = {
            "provider": selected_provider,
            "tool_used": route.get("tool_name"),
            "tool_action": route.get("args", {}).get("action"),
            "tool_reason": route["reason"],
            "missing_tool": missing_tool,
            "requires_confirmation": False,
            "executed": False,
            "model_used_after_tool": False,
        }
        write_audit_event(
            "chat.tool_route",
            {
                "conversation_id": conversation_id,
                "provider": selected_provider,
                "tool_name": route.get("tool_name"),
                "action": route.get("args", {}).get("action"),
                "path": route.get("args", {}).get("path"),
                "confirmation_required": False,
                "executed": False,
                "reason": route["reason"],
            },
        )
        return AssistantResponse(conversation_id, selected_provider, reply, [], metadata)

    def _save_conversation_summary(
        self,
        conversation_id: str,
        user_message: str,
        assistant_reply: str,
        provider: str,
        vector_store: LocalVectorStore,
    ) -> None:
        if len(user_message.strip()) < 12 and len(assistant_reply.strip()) < 12:
            return
        summary = (
            f"User asked: {user_message.strip()}\n"
            f"Jarvis answered using {provider}: {assistant_reply.strip()[:1200]}"
        )
        title = user_message.strip().splitlines()[0][:120] or "Conversation summary"
        memory = self.memory_db.create_memory(
            memory_type="conversation_summary",
            title=title,
            content=summary,
            tags=["conversation", provider],
            source=f"conversation:{conversation_id}",
            confidence=0.7,
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


def _build_prompt(message: str, context_prefix: str = "") -> str:
    return f"System policy:\n{MEMORY_SYSTEM_POLICY}\n{TOOL_SYSTEM_POLICY}\n\n{context_prefix}User message:\n{message}"


def _build_context_prefix(recalled: list[dict[str, str]]) -> str:
    if not recalled:
        return ""
    facts = "\n".join(f"- [{item['memory_type']}] {item['title']}: {item['content']}" for item in recalled)
    return f"Relevant local memory. Use only if directly helpful and do not reveal internal IDs:\n{facts}\n\n"


def _build_trusted_rag_prompt(message: str, documents: list[dict[str, Any]]) -> str:
    doc_blocks = []
    for index, document in enumerate(documents, start=1):
        source_id = f"S{index}"
        tables = "\n\n".join(str(table) for table in document.get("tables") or [])
        lists = "\n\n".join(str(item_list) for item_list in document.get("lists") or [])
        body_parts = [str(document.get("text") or "")]
        if tables:
            body_parts.append(f"Tables:\n{tables}")
        if lists:
            body_parts.append(f"Lists:\n{lists}")
        doc_blocks.append(
            "\n".join(
                [
                    f"[{source_id}] {document.get('title') or 'Untitled'}",
                    f"Source: {document.get('source_name') or ''}",
                    f"URL: {document.get('url') or ''}",
                    f"Published: {document.get('published') or 'unknown'}",
                    "Text:",
                    "\n\n".join(body_parts),
                ]
            )
        )
    return (
        "System Prompt:\n"
        "Answer ONLY using provided text. No prior knowledge. No guessing. Cite sources for every claim. "
        "If info is missing, reply: INSUFFICIENT_TRUSTED_DATA.\n\n"
        f"User query:\n{message}\n\n"
        "Trusted source documents:\n"
        + "\n\n---\n\n".join(doc_blocks)
    )


def _answer_from_tool_result(tool_name: str, result: dict[str, Any]) -> str:
    if error := result.get("error"):
        return _tool_error_message(tool_name, str(error))
    if tool_name == "filesystem_manager":
        return _filesystem_answer(result)
    if tool_name == "web_search":
        return _web_search_answer(result)
    if tool_name == "echo_tool":
        return str(result.get("text") or result)
    return str(result)


def _chat_may_confirm_tool_run(tool_name: str, args: dict[str, Any]) -> bool:
    if tool_name != "filesystem_manager":
        return True
    return args.get("action") in {
        "tree",
        "list",
        "read",
        "info",
        "search_names",
        "search_text",
        "create_file",
        "create_folder",
        "append_file",
    }


def _tool_metadata(
    selected_provider: str,
    route: dict[str, Any],
    executed: bool,
    tool_result_ok: bool,
) -> dict[str, Any]:
    args = dict(route.get("args") or {})
    return {
        "provider": selected_provider,
        "tool_used": route.get("tool_name"),
        "tool_action": args.get("action"),
        "tool_reason": route["reason"],
        "tool_args": args,
        "requires_confirmation": bool(route.get("requires_confirmation")),
        "approval_phrase": route.get("approval_phrase"),
        "executed": executed,
        "tool_result_ok": tool_result_ok,
        "model_used_after_tool": False,
    }


def _approval_metadata(
    selected_provider: str,
    pending: PendingProtectedAction | None,
    *,
    executed: bool,
    accepted: bool,
    tool_result_ok: bool = False,
) -> dict[str, Any]:
    return {
        "provider": selected_provider,
        "tool_used": pending.tool_name if pending else None,
        "tool_action": pending.action if pending else None,
        "requires_confirmation": False,
        "executed": executed,
        "approval_accepted": accepted,
        "tool_result_ok": tool_result_ok,
        "model_used_after_tool": False,
    }


def _tool_audit_payload(
    conversation_id: str,
    selected_provider: str,
    route: dict[str, Any],
    executed: bool,
) -> dict[str, Any]:
    args = dict(route.get("args") or {})
    return {
        "conversation_id": conversation_id,
        "provider": selected_provider,
        "tool_name": route.get("tool_name"),
        "action": args.get("action"),
        "path": args.get("path"),
        "confirmation_required": bool(route.get("requires_confirmation")),
        "executed": executed,
        "reason": route["reason"],
    }


def _confirmation_message(route: dict[str, Any]) -> str:
    args = dict(route.get("args") or {})
    action = args.get("action")
    path = (
        route.get("approval_phrase", "").split(": ", 1)[-1]
        or str(args.get("path") or args.get("project_path") or args.get("target_file") or "that target")
    )
    approval_phrase = route.get("approval_phrase", "")
    if str(approval_phrase).startswith("APPROVE ACTION:"):
        return (
            "This plugin action requires confirmation. I can proceed, but I need this exact approval phrase:\n\n"
            f"{approval_phrase}"
        )
    if action == "delete":
        verb = "Deleting files is protected"
        action_text = "delete"
    elif action == "overwrite_file":
        verb = "Overwriting files is protected"
        action_text = "overwrite"
    else:
        verb = "Renaming files is protected"
        action_text = "rename"
    return (
        f"{verb}. I can {action_text} {path}, but I need admin confirmation and this exact approval phrase:\n\n"
        f"{approval_phrase}"
    )


def _blocked_tool_message(route: dict[str, Any]) -> str:
    return f"I cannot perform that filesystem request. {route['reason']}"


def _filesystem_answer(result: dict[str, Any]) -> str:
    if tree := result.get("tree"):
        return str(tree)
    if "content" in result:
        path = result.get("path", "file")
        return f"{path}\n\n{result['content']}"
    if entries := result.get("entries"):
        path = result.get("path", "requested folder")
        lines = [f"{path}:"]
        for entry in entries:
            suffix = "/" if entry.get("type") == "directory" else ""
            lines.append(f"- {entry.get('name', '')}{suffix}")
        return "\n".join(lines)
    if created := result.get("created"):
        return f"Created: {created}"
    if appended := result.get("appended"):
        return f"Appended to: {appended}"
    if deleted := result.get("deleted"):
        return f"Deleted {deleted}"
    if overwritten := result.get("overwritten"):
        return f"Overwritten: {overwritten}"
    if renamed_to := result.get("renamed_to"):
        return f"Renamed {result.get('renamed_from', 'file')} to {renamed_to}"
    return str(result)


def _web_search_answer(result: dict[str, Any]) -> str:
    if result.get("ok") is False:
        return _tool_error_message("web_search", str(result.get("error", "Search failed.")))
    if answer := result.get("answer"):
        return str(answer)
    results = result.get("results") or []
    if not results:
        return "I used web_search, but it did not return usable results. I will not invent current or live information."
    lines = [f"Search results for: {result.get('query', '')}".rstrip()]
    for item in results:
        title = item.get("title") or "Untitled result"
        snippet = item.get("snippet") or ""
        url = item.get("url") or ""
        detail = f"- {title}"
        if snippet:
            detail += f": {snippet}"
        if url:
            detail += f" ({url})"
        lines.append(detail)
    if note := result.get("note"):
        lines.append(str(note))
    return "\n".join(lines)


def _tool_error_message(tool_name: str, error: str) -> str:
    if tool_name == "filesystem_manager":
        return f"I cannot inspect that filesystem path because filesystem_manager returned an error: {error}"
    if tool_name == "web_search":
        return f"I cannot verify current or web information because web_search returned an error: {error}"
    return f"I cannot use {tool_name} because it returned an error: {error}"


def _missing_tool_message(tool_name: str) -> str:
    if tool_name == "filesystem_manager":
        return "I cannot inspect that yet because no suitable filesystem tool is available."
    if tool_name == "web_search":
        return "I cannot verify current or live information yet because no suitable web search tool is available."
    return f"I cannot do that yet because no suitable {tool_name} tool is available."


def _classify_current_info_query(message: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", message.strip().lower())
    matched = [keyword for keyword in CURRENT_INFO_KEYWORDS if keyword in normalized]
    return {
        "current_info": bool(matched),
        "matched_keywords": matched,
        "classification": "current_info" if matched else "general",
    }


def _web_search_route(message: str, matched_keywords: list[str]) -> dict[str, Any]:
    return {
        "use_tool": True,
        "tool_name": "web_search",
        "args": {"query": message},
        "reason": "Pre-LLM current/live information routing.",
        "requires_tool": True,
        "missing_tool": None,
        "requires_confirmation": False,
        "blocked": False,
        "matched_keywords": matched_keywords,
    }


def _tool_confidence(tool_result: dict[str, Any]) -> float:
    raw = tool_result.get("confidence", 0.0)
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        label = raw.strip().lower()
        if label == "high":
            return 0.8
        if label == "medium":
            return 0.55
        if label == "low":
            return 0.25
        try:
            return float(label)
        except ValueError:
            return 0.0
    return 0.0


def _should_start_learning(tool_result: dict[str, Any]) -> bool:
    if tool_result.get("mode") == "needs_sources":
        return True
    if tool_result.get("teach_request"):
        return True
    error = str(tool_result.get("error") or "").lower()
    answer = str(tool_result.get("answer") or "").lower()
    return "no trusted source category" in error or "no trusted source category" in answer


def _extract_urls(message: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>()\"']+", message)
    return _dedupe(url.rstrip(".,;:!?") for url in urls)


def _generate_category_name(query: str, suggested: str = "") -> str:
    candidate = suggested.strip().lower()
    if not candidate or candidate in {"new_topic", "latest", "current", "news", "general_news"}:
        words = _category_words(query)
        if "news" in query.lower() and "news" not in words:
            words.append("news")
        candidate = "_".join(words) or "new_topic"
    candidate = re.sub(r"[^a-z0-9_]+", "_", candidate)
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    return candidate or "new_topic"


def _category_words(query: str) -> list[str]:
    stop = {
        "what",
        "when",
        "where",
        "which",
        "with",
        "from",
        "about",
        "please",
        "show",
        "tell",
        "give",
        "latest",
        "current",
        "today",
        "tomorrow",
        "the",
        "and",
        "for",
        "are",
        "is",
        "any",
        "new",
    }
    return [word for word in re.findall(r"[a-zA-Z0-9]+", query.lower()) if len(word) > 2 and word not in stop][:5]


def _extract_keywords(query: str) -> list[str]:
    return _dedupe(_category_words(query))


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out
