from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


class LocalVectorStore:
    def __init__(self, path: str, dimensions: int = 64) -> None:
        self.path = Path(path)
        self.dimensions = dimensions
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, document_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        data = self._load()
        data[document_id] = {
            "text": text,
            "metadata": metadata or {},
            "embedding": self._embed(text),
        }
        self._save(data)

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_embedding = self._embed(query)
        results = []
        for document_id, item in self._load().items():
            score = _cosine(query_embedding, item["embedding"])
            results.append({"id": document_id, "score": score, "text": item["text"], "metadata": item["metadata"]})
        return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]

    def delete(self, document_id: str) -> None:
        data = self._load()
        data.pop(document_id, None)
        self._save(data)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))
