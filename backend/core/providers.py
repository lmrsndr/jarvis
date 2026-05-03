from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from core.config import Settings


class ProviderError(RuntimeError):
    pass


EXTERNAL_PROVIDERS = {"openai", "gemini"}
PROVIDER_ALIASES = {
    "local": "ollama",
    "ollama": "ollama",
    "openai": "openai",
    "gemini": "gemini",
}
_selected_provider = "ollama"


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    provider: str
    model: str
    external: bool = False

    @property
    def metadata(self) -> dict[str, Any]:
        metadata = {
            "provider": self.provider,
            "model": self.model,
            "external_provider_used": self.external,
        }
        if self.external:
            metadata["safety_notice"] = f"External provider used: {self.provider}"
        return metadata


class ChatProvider(ABC):
    name: str
    model: str
    external: bool = False

    @abstractmethod
    async def chat(self, message: str, history: list[dict[str, str]] | None = None) -> ProviderResponse:
        raise NotImplementedError


class OllamaProvider(ChatProvider):
    name = "ollama"
    external = False

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    async def chat(self, message: str, history: list[dict[str, str]] | None = None) -> ProviderResponse:
        messages = [{"role": item["role"], "content": item["content"]} for item in history or []]
        messages.append({"role": "user", "content": message})

        prompt = "\n".join(
            f"{item['role'].upper()}: {item['content']}"
            for item in messages
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        return ProviderResponse(
            content=data.get("response", "").strip(),
            provider=self.name,
            model=self.model,
            external=self.external,
        )


class OpenAIProvider(ChatProvider):
    name = "openai"
    external = True

    def __init__(self, settings: Settings, explicit: bool = False) -> None:
        if not explicit:
            raise ProviderError("OpenAI requires explicit provider selection.")
        if not settings.openai_api_key:
            raise ProviderError("OpenAI is disabled because OPENAI_API_KEY is not set.")
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model

    async def chat(self, message: str, history: list[dict[str, str]] | None = None) -> ProviderResponse:
        input_items: list[dict[str, Any]] = [
            {"role": item["role"], "content": item["content"]} for item in history or []
        ]
        input_items.append({"role": "user", "content": message})
        payload = {"model": self.model, "input": input_items}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        data = response.json()
        if text := data.get("output_text"):
            content = text.strip()
        else:
            content = _extract_openai_text(data).strip()
        return ProviderResponse(content=content, provider=self.name, model=self.model, external=self.external)


class GeminiProvider(ChatProvider):
    name = "gemini"
    external = True

    def __init__(self, settings: Settings, explicit: bool = False) -> None:
        if not explicit:
            raise ProviderError("Gemini requires explicit provider selection.")
        if not settings.gemini_api_key:
            raise ProviderError("Gemini is disabled because GEMINI_API_KEY is not set.")
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model

    async def chat(self, message: str, history: list[dict[str, str]] | None = None) -> ProviderResponse:
        contents = []
        for item in history or []:
            role = "model" if item["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": item["content"]}]})
        contents.append({"role": "user", "parts": [{"text": message}]})
        payload = {"contents": contents}
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ProviderResponse(content="", provider=self.name, model=self.model, external=self.external)
        parts = candidates[0].get("content", {}).get("parts", [])
        content = "".join(part.get("text", "") for part in parts).strip()
        return ProviderResponse(content=content, provider=self.name, model=self.model, external=self.external)


def normalize_provider_name(name: str | None) -> str:
    provider_name = (name or "local").lower()
    if provider_name not in PROVIDER_ALIASES:
        raise ProviderError(f"Unknown provider: {provider_name}")
    return PROVIDER_ALIASES[provider_name]


def get_provider(name: str | None, settings: Settings, explicit: bool = False) -> ChatProvider:
    provider_name = normalize_provider_name(name or get_selected_provider())
    if provider_name == "ollama":
        return OllamaProvider(settings)
    if provider_name == "openai":
        return OpenAIProvider(settings, explicit=explicit)
    if provider_name == "gemini":
        return GeminiProvider(settings, explicit=explicit)
    raise ProviderError(f"Unknown provider: {provider_name}")


def get_selected_provider() -> str:
    return _selected_provider


def set_selected_provider(name: str, settings: Settings) -> str:
    global _selected_provider

    provider_name = normalize_provider_name(name)
    if provider_name in EXTERNAL_PROVIDERS and not settings.provider_available(provider_name):
        raise ProviderError(f"{provider_name} is disabled because its API key is not set.")

    _selected_provider = provider_name
    return _selected_provider


def provider_status(settings: Settings) -> list[dict[str, Any]]:
    selected = get_selected_provider()
    return [
        {
            "name": "local",
            "provider": "ollama",
            "available": True,
            "default": True,
            "selected": selected == "ollama",
            "external": False,
            "requires_explicit_selection": False,
        },
        {
            "name": "openai",
            "provider": "openai",
            "available": bool(settings.openai_api_key),
            "default": False,
            "selected": selected == "openai",
            "external": True,
            "requires_explicit_selection": True,
        },
        {
            "name": "gemini",
            "provider": "gemini",
            "available": bool(settings.gemini_api_key),
            "default": False,
            "selected": selected == "gemini",
            "external": True,
            "requires_explicit_selection": True,
        },
    ]


def _extract_openai_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(content.get("text", ""))
    return "\n".join(chunk for chunk in chunks if chunk)
