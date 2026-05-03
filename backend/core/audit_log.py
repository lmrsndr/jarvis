from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT_DIR


LOG_PATH = ROOT_DIR / "storage" / "logs" / "audit.jsonl"


def write_audit_event(event_type: str, payload: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=True) + "\n")
