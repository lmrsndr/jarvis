from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


APPROVAL_PREFIXES = ("APPROVE DELETE:", "APPROVE OVERWRITE:", "APPROVE RENAME:", "APPROVE ACTION:")
DEFAULT_EXPIRY_SECONDS = 5 * 60


@dataclass(frozen=True)
class PendingProtectedAction:
    conversation_id: str
    tool_name: str
    action: str
    args: dict[str, Any]
    resolved_path: str
    approval_phrase: str
    created_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or _now()) >= self.expires_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "tool_name": self.tool_name,
            "action": self.action,
            "args": dict(self.args),
            "resolved_path": self.resolved_path,
            "approval_phrase": self.approval_phrase,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


_PENDING_PROTECTED_ACTIONS: dict[str, PendingProtectedAction] = {}


def is_approval_message(message: str) -> bool:
    text = message.strip()
    return any(text.startswith(prefix) for prefix in APPROVAL_PREFIXES)


def store_pending_action(
    conversation_id: str,
    route: dict[str, Any],
    *,
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    now: datetime | None = None,
) -> PendingProtectedAction:
    created_at = now or _now()
    args = dict(route.get("args") or {})
    args.setdefault("admin_confirmed", False)
    args.setdefault("approval_text", "")
    action = str(args.get("action") or "run")
    target_path = str(args.get("path") or args.get("project_path") or args.get("target_file") or args.get("destination") or "")
    pending = PendingProtectedAction(
        conversation_id=conversation_id,
        tool_name=str(route["tool_name"]),
        action=action,
        args=args,
        resolved_path=_absolute_path(target_path) if target_path else "",
        approval_phrase=str(route["approval_phrase"]),
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=expiry_seconds),
    )
    _PENDING_PROTECTED_ACTIONS[conversation_id] = pending
    return pending


def get_pending_action(conversation_id: str) -> PendingProtectedAction | None:
    return _PENDING_PROTECTED_ACTIONS.get(conversation_id)


def clear_pending_action(conversation_id: str) -> None:
    _PENDING_PROTECTED_ACTIONS.pop(conversation_id, None)


def clear_all_pending_actions() -> None:
    _PENDING_PROTECTED_ACTIONS.clear()


def _absolute_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _now() -> datetime:
    return datetime.now(timezone.utc)
