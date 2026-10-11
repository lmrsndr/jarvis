"""Owner-installed declarative skills; no Python imports or shell evaluation."""

from __future__ import annotations
import asyncio
import json
from urllib.parse import urlparse
import httpx
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, model_validator


class SkillManifest(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    version: str
    description: str = Field(max_length=1000)
    input_schema: dict
    transport: str = "http"
    endpoint: str = ""
    command: list[str] = Field(default_factory=list)
    token_env: str = ""
    resources: list[str] = Field(default_factory=list)
    risk: str = "approval"
    idempotent: bool = False
    supports_checkpoint: bool = False
    timeout_seconds: int = Field(default=120, ge=5, le=86400)
    success_schema: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"ok": {"const": True}},
            "required": ["ok"],
        }
    )

    @model_validator(mode="after")
    def validate_contract(self):
        Draft202012Validator.check_schema(self.input_schema)
        Draft202012Validator.check_schema(self.success_schema)
        if self.input_schema.get("type") != "object":
            raise ValueError("input_schema must describe an object")
        if self.transport not in ("http", "command"):
            raise ValueError("Unsupported transport")
        if self.risk not in ("approval", "automatic"):
            raise ValueError("Unsupported risk policy")
        if self.transport == "http":
            u = urlparse(self.endpoint)
            if (
                u.scheme not in ("http", "https")
                or not u.hostname
                or u.username
                or u.password
            ):
                raise ValueError(
                    "Provide a full HTTP endpoint without embedded credentials"
                )
            if u.scheme == "http" and u.hostname not in (
                "localhost",
                "127.0.0.1",
                "::1",
            ):
                raise ValueError("Non-local endpoints require HTTPS")
        if self.transport == "command" and (not self.command or not self.command[0]):
            raise ValueError("A command executable is required")
        return self


async def execute_skill(manifest, args, job):
    Draft202012Validator(manifest["input_schema"]).validate(args)
    request = {
        "job_id": job["id"],
        "request_id": job["request_id"],
        "args": args,
        "checkpoint": job["checkpoint"],
    }
    if manifest["transport"] == "http":
        import os

        headers = {"Idempotency-Key": job["request_id"]}
        if manifest.get("token_env"):
            token = os.getenv(manifest["token_env"], "")
            if not token:
                raise ValueError("Skill credential is not configured")
            headers["Authorization"] = "Bearer " + token
        async with httpx.AsyncClient(
            trust_env=False, timeout=manifest["timeout_seconds"], follow_redirects=False
        ) as client:
            r = await client.post(manifest["endpoint"], json=request, headers=headers)
            r.raise_for_status()
            result = r.json()
    else:
        p = await asyncio.create_subprocess_exec(
            *manifest["command"],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                p.communicate(json.dumps(request).encode()), manifest["timeout_seconds"]
            )
            if p.returncode:
                raise ValueError("Skill process failed; exit code " + str(p.returncode))
            if len(stdout) > 2_000_000:
                raise ValueError("Skill output exceeds 2 MB")
            result = json.loads(stdout)
        except BaseException:
            if p.returncode is None:
                p.kill()
                await p.wait()
            raise
    if not isinstance(result, dict):
        raise ValueError("Skill must return a JSON object")
    # A checkpoint pause is a distinct successful protocol response, not completion.
    if (
        result.get("paused") is True
        and manifest.get("supports_checkpoint")
        and isinstance(result.get("checkpoint"), dict)
    ):
        return result
    Draft202012Validator(manifest["success_schema"]).validate(result)
    if result.get("ok") is not True:
        raise ValueError("Skill did not confirm success")
    return result
