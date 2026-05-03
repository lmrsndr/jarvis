from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MemoryType = Literal[
    "fact",
    "project",
    "task",
    "script",
    "log",
    "search_result",
    "conversation_summary",
    "system_change",
]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    provider: str | None = None
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    provider: str
    message: str
    recalled: list[dict[str, str]]
    metadata: dict = Field(default_factory=dict)


class MemoryCreate(BaseModel):
    memory_type: MemoryType = "fact"
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryResponse(BaseModel):
    id: int
    memory_type: MemoryType
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    source: str
    confidence: float
    created_at: str | None = None
    updated_at: str | None = None


class MemoryDeleteRequest(BaseModel):
    admin_password: str = Field(min_length=1)
