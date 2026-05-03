from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Any


class MemoryDatabase:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'manual',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def add_message(self, conversation_id: str, role: str, content: str, provider: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO messages (conversation_id, role, content, provider) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, provider),
            )

    def get_recent_messages(self, conversation_id: str, limit: int = 12) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def create_memory(
        self,
        memory_type: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memories (memory_type, title, content, tags, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (memory_type, title, content, json.dumps(tags or []), source, confidence),
            )
            row = connection.execute(
                """
                SELECT id, memory_type, title, content, tags, source, confidence, created_at, updated_at
                FROM memories
                WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        return _memory_from_row(row)

    def list_memories(self, limit: int = 50, memory_type: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if memory_type:
                rows = connection.execute(
                    """
                    SELECT id, memory_type, title, content, tags, source, confidence, created_at, updated_at
                    FROM memories
                    WHERE memory_type = ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (memory_type, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, memory_type, title, content, tags, source, confidence, created_at, updated_at
                    FROM memories
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, memory_type, title, content, tags, source, confidence, created_at, updated_at
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
        return _memory_from_row(row) if row else None

    def get_memories_by_ids(self, memory_ids: list[int]) -> list[dict[str, Any]]:
        if not memory_ids:
            return []
        placeholders = ",".join("?" for _ in memory_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, memory_type, title, content, tags, source, confidence, created_at, updated_at
                FROM memories
                WHERE id IN ({placeholders})
                """,
                memory_ids,
            ).fetchall()
        memories = {_memory_from_row(row)["id"]: _memory_from_row(row) for row in rows}
        return [memories[memory_id] for memory_id in memory_ids if memory_id in memories]

    def search_memories(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        like_query = f"%{query}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, memory_type, title, content, tags, source, confidence, created_at, updated_at
                FROM memories
                WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? OR source LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (like_query, like_query, like_query, like_query, limit),
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def delete_memory(self, memory_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cursor.rowcount > 0


def _memory_from_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["tags"] = json.loads(data.get("tags") or "[]")
    except json.JSONDecodeError:
        data["tags"] = []
    return data
