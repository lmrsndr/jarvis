from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.config import Settings, get_settings
from memory.db import MemoryDatabase
from memory.models import MemoryCreate, MemoryDeleteRequest, MemoryResponse, MemoryType
from memory.vector_store import LocalVectorStore


router = APIRouter(prefix="/api/memory", tags=["memory"])


def get_memory_db(settings: Settings = Depends(get_settings)) -> MemoryDatabase:
    memory_db = MemoryDatabase(settings.memory_db_path)
    memory_db.init()
    return memory_db


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    memory: MemoryCreate,
    settings: Settings = Depends(get_settings),
    memory_db: MemoryDatabase = Depends(get_memory_db),
):
    created = memory_db.create_memory(
        memory_type=memory.memory_type,
        title=memory.title,
        content=memory.content,
        tags=memory.tags,
        source=memory.source,
        confidence=memory.confidence,
    )
    _index_memory(settings, created)
    return created


@router.get("")
def list_memories(
    limit: int = Query(50, ge=1, le=200),
    memory_type: MemoryType | None = None,
    memory_db: MemoryDatabase = Depends(get_memory_db),
):
    return {"memories": memory_db.list_memories(limit=limit, memory_type=memory_type)}


@router.get("/search")
def search_memory(
    q: str = Query(min_length=1),
    limit: int = Query(10, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    memory_db: MemoryDatabase = Depends(get_memory_db),
):
    vector_matches = LocalVectorStore(settings.vector_path).search(q, limit=limit)
    vector_ids = [int(match["id"]) for match in vector_matches if str(match["id"]).isdigit()]
    memories = memory_db.get_memories_by_ids(vector_ids)
    by_id = {memory["id"]: memory for memory in memories}
    for match in vector_matches:
        if str(match["id"]).isdigit() and int(match["id"]) in by_id:
            by_id[int(match["id"])]["score"] = match["score"]

    existing = {memory["id"] for memory in memories}
    text_matches = [memory for memory in _search_memory_candidates(memory_db, q, limit) if memory["id"] not in existing]
    memories = (text_matches + memories)[:limit]

    return {"memories": memories}


@router.get("/{memory_id}", response_model=MemoryResponse)
def get_memory(memory_id: int, memory_db: MemoryDatabase = Depends(get_memory_db)):
    memory = memory_db.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    return memory


def _search_memory_candidates(memory_db: MemoryDatabase, query: str, limit: int) -> list[dict[str, Any]]:
    candidates: dict[int, dict[str, Any]] = {}
    search_terms = [query, *sorted(set(re.findall(r"[a-zA-Z0-9_]+", query)))]
    for term in search_terms:
        if len(term) < 2:
            continue
        for memory in memory_db.search_memories(term, limit=limit):
            candidates.setdefault(memory["id"], memory)
    return list(candidates.values())


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: int,
    confirmation: MemoryDeleteRequest,
    settings: Settings = Depends(get_settings),
    memory_db: MemoryDatabase = Depends(get_memory_db),
):
    _verify_admin_password(confirmation.admin_password, settings)
    deleted = memory_db.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    LocalVectorStore(settings.vector_path).delete(str(memory_id))
    return {"deleted": True, "id": memory_id}


def _index_memory(settings: Settings, memory: dict) -> None:
    text = f"{memory['title']}\n{memory['content']}\n{' '.join(memory['tags'])}"
    LocalVectorStore(settings.vector_path).add(
        str(memory["id"]),
        text,
        {
            "memory_type": memory["memory_type"],
            "title": memory["title"],
            "source": memory["source"],
        },
    )


def _verify_admin_password(password: str, settings: Settings) -> None:
    expected_hash = settings.admin_password_hash
    if not expected_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Memory deletion is disabled until JARVIS_ADMIN_PASSWORD_HASH is set.",
        )

    provided_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(provided_hash, expected_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin password.")
