from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


PermissionLevel = Literal["safe", "medium", "dangerous"]
ExecutionMode = Literal["direct_answer", "grounded_answer", "actuate", "dangerous_write"]


class PluginSchema(BaseModel):
    name: str | None = None
    tool_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str
    intents: list[str] = Field(default_factory=list)
    execution_mode: ExecutionMode = "direct_answer"
    risk_level: PermissionLevel | None = None
    entry_file: str = "tool.py"
    entry_function: str = "run"
    permissions: PermissionLevel = "safe"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    requires_password_for: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        name = normalized.get("name") or normalized.get("tool_name")
        if name and not normalized.get("tool_name"):
            normalized["tool_name"] = name
        if name and not normalized.get("name"):
            normalized["name"] = name
        if "parameters" in normalized and "input_schema" not in normalized:
            normalized["input_schema"] = normalized["parameters"]
        if "risk_level" not in normalized and "permissions" in normalized:
            normalized["risk_level"] = normalized["permissions"]
        if "permissions" not in normalized and "risk_level" in normalized:
            normalized["permissions"] = normalized["risk_level"]
        return normalized

    @model_validator(mode="after")
    def keep_aliases_in_sync(self) -> "PluginSchema":
        if self.name is None:
            self.name = self.tool_name
        if self.risk_level is None:
            self.risk_level = self.permissions
        return self
