from __future__ import annotations

import pytest

from core.config import Settings
from core.providers import (
    GeminiProvider,
    OpenAIProvider,
    ProviderError,
    ProviderResponse,
    normalize_provider_name,
    provider_status,
    set_selected_provider,
)


def test_local_alias_maps_to_ollama() -> None:
    assert normalize_provider_name("local") == "ollama"
    assert normalize_provider_name("ollama") == "ollama"


def test_external_provider_selection_requires_api_key() -> None:
    settings = Settings(openai_api_key="", gemini_api_key="")

    assert set_selected_provider("local", settings) == "ollama"
    with pytest.raises(ProviderError):
        set_selected_provider("openai", settings)
    with pytest.raises(ProviderError):
        set_selected_provider("gemini", settings)


def test_external_provider_constructors_require_explicit_selection() -> None:
    settings = Settings(openai_api_key="test-openai", gemini_api_key="test-gemini")

    with pytest.raises(ProviderError):
        OpenAIProvider(settings)
    with pytest.raises(ProviderError):
        GeminiProvider(settings)

    assert OpenAIProvider(settings, explicit=True).name == "openai"
    assert GeminiProvider(settings, explicit=True).name == "gemini"


def test_provider_status_marks_selected_provider() -> None:
    settings = Settings(openai_api_key="test-openai", gemini_api_key="")
    set_selected_provider("openai", settings)

    providers = provider_status(settings)
    assert next(item for item in providers if item["name"] == "openai")["selected"] is True
    assert next(item for item in providers if item["name"] == "gemini")["available"] is False

    set_selected_provider("local", settings)


def test_external_provider_response_metadata_is_explicit() -> None:
    response = ProviderResponse(content="hello", provider="openai", model="test-model", external=True)

    assert response.metadata["external_provider_used"] is True
    assert response.metadata["provider"] == "openai"
    assert "External provider used" in response.metadata["safety_notice"]
