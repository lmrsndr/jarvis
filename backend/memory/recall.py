from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from memory.db import MemoryDatabase
from memory.vector_store import LocalVectorStore


DEFAULT_RECALL_LIMIT = 3
DEFAULT_RELEVANCE_THRESHOLD = 0.25

IDENTITY_MEMORY_TYPES = ["fact"]
PROJECT_MEMORY_TYPES = ["project", "task", "script", "log", "search_result", "conversation_summary", "system_change", "fact"]
CONVERSATION_MEMORY_TYPES = ["conversation_summary", "project", "task", "system_change", "log", "fact"]
ALL_MEMORY_TYPES = ["fact", "project", "task", "script", "log", "search_result", "conversation_summary", "system_change"]

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "did",
    "do",
    "does",
    "from",
    "how",
    "i",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "this",
    "to",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
}


@dataclass(frozen=True)
class MemoryDecision:
    use_memory: bool
    allowed_memory_types: list[str]
    reason: str
    allow_identity: bool = False


def decide_memory_use(query: str) -> MemoryDecision:
    text = query.strip().lower()
    if not text:
        return MemoryDecision(False, [], "empty request")

    identity_patterns = [
        r"\bwhat(?:'s| is) my name\b",
        r"\bwho am i\b",
        r"\bdo you know my name\b",
        r"\bmy name\b",
        r"\bcall me\b",
        r"\babout me\b",
    ]
    if any(re.search(pattern, text) for pattern in identity_patterns):
        return MemoryDecision(True, IDENTITY_MEMORY_TYPES.copy(), "request asks for user identity or personal facts", True)

    continuity_patterns = [
        r"\bremember\b",
        r"\brecall\b",
        r"\bcontinue\b",
        r"\bresume\b",
        r"\bprevious\b",
        r"\blast time\b",
        r"\blast session\b",
        r"\blast conversation\b",
        r"\bwhere were we\b",
        r"\bpick up\b",
        r"\bwhat did we\b",
    ]
    if any(re.search(pattern, text) for pattern in continuity_patterns):
        return MemoryDecision(True, CONVERSATION_MEMORY_TYPES.copy(), "request asks for continuity with stored conversation or project context")

    local_project_patterns = [
        r"\bjarvis\b",
        r"\blocal setup\b",
        r"\bthis project\b",
        r"\bour project\b",
        r"\bproject\b",
        r"\brepo(?:sitory)?\b",
        r"\bcodebase\b",
        r"\bbackend\b",
        r"\bfrontend\b",
        r"\bfile(?:s)?\b",
        r"\bfolder(?:s)?\b",
        r"\bpath(?:s)?\b",
        r"\bplugin(?:s)?\b",
        r"\bconfigured?\b",
        r"\bconfiguration\b",
        r"\bsqlite\b",
        r"\bollama\b",
    ]
    if any(re.search(pattern, text) for pattern in local_project_patterns):
        return MemoryDecision(True, PROJECT_MEMORY_TYPES.copy(), "request is about Jarvis, local setup, project, or files")

    personal_context_patterns = [
        r"\bmy preference(?:s)?\b",
        r"\bmy favorite(?:s)?\b",
        r"\bmy setup\b",
        r"\bmy machine\b",
        r"\bmy computer\b",
        r"\bmy environment\b",
        r"\bmy account\b",
    ]
    if any(re.search(pattern, text) for pattern in personal_context_patterns):
        return MemoryDecision(True, ALL_MEMORY_TYPES.copy(), "request asks about user-specific stored context", True)

    return MemoryDecision(False, [], "general request can be answered without local memory")


def recall_context(
    memory_db: MemoryDatabase,
    vector_store: LocalVectorStore,
    query: str,
    limit: int = DEFAULT_RECALL_LIMIT,
    allowed_memory_types: list[str] | None = None,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    allow_identity: bool = False,
) -> list[dict[str, str]]:
    if not query.strip():
        return []
    limit = max(1, limit)
    allowed_types = set(allowed_memory_types or ALL_MEMORY_TYPES)
    vector_matches = [
        match
        for match in vector_store.search(query, limit=max(limit * 4, limit))
        if float(match.get("score", 0.0)) >= relevance_threshold
    ]
    score_by_id = {str(match["id"]): float(match.get("score", 0.0)) for match in vector_matches}
    vector_ids = [int(match["id"]) for match in vector_matches if str(match["id"]).isdigit()]
    memories = memory_db.get_memories_by_ids(vector_ids)
    memories = [
        item
        for item in memories
        if _memory_allowed(item, allowed_types, allow_identity)
    ][:limit]
    if len(memories) < limit:
        existing = {item["id"] for item in memories}
        text_candidates = _text_candidates(memory_db, query, limit=limit * 4)
        text_matches = [
            item
            for item in text_candidates
            if item["id"] not in existing
            and _memory_allowed(item, allowed_types, allow_identity)
            and _lexical_relevance(query, item) >= relevance_threshold
        ]
        memories.extend(text_matches[: limit - len(memories)])
    return [
        {
            "id": str(item["id"]),
            "memory_type": item["memory_type"],
            "title": item["title"],
            "content": item["content"],
            "source": item["source"],
            "score": f"{score_by_id.get(str(item['id']), _lexical_relevance(query, item)):.3f}",
        }
        for item in memories[:limit]
    ]


def _memory_allowed(memory: dict[str, Any], allowed_types: set[str], allow_identity: bool) -> bool:
    if memory["memory_type"] not in allowed_types:
        return False
    if not allow_identity and _is_identity_memory(memory):
        return False
    return True


def _text_candidates(memory_db: MemoryDatabase, query: str, limit: int) -> list[dict[str, Any]]:
    candidates: dict[int, dict[str, Any]] = {}
    for token in sorted(_tokens(query)):
        for item in memory_db.search_memories(token, limit=limit):
            candidates.setdefault(item["id"], item)
    return sorted(candidates.values(), key=lambda item: _lexical_relevance(query, item), reverse=True)


def _is_identity_memory(memory: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(memory.get("memory_type", "")),
            str(memory.get("title", "")),
            str(memory.get("content", "")),
            " ".join(str(tag) for tag in memory.get("tags", [])),
            str(memory.get("source", "")),
        ]
    ).lower()
    identity_terms = ("user name", "user's name", "my name", "identity", "profile", "birthday", "address")
    return memory.get("memory_type") == "fact" and any(term in text for term in identity_terms)


def _lexical_relevance(query: str, memory: dict[str, Any]) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    memory_text = " ".join(
        [
            str(memory.get("title", "")),
            str(memory.get("content", "")),
            " ".join(str(tag) for tag in memory.get("tags", [])),
            str(memory.get("source", "")),
        ]
    )
    memory_tokens = _tokens(memory_text)
    if not memory_tokens:
        return 0.0
    return len(query_tokens & memory_tokens) / len(query_tokens)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower()) if token not in _STOPWORDS and len(token) > 1}
