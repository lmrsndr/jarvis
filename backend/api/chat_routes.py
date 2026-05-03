from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from core.assistant import Assistant
from core.config import Settings, get_settings
from core.providers import ProviderError
from memory.db import MemoryDatabase
from memory.models import ChatRequest, ChatResponse


router = APIRouter(prefix="/api/chat", tags=["chat"])


def get_assistant(settings: Settings = Depends(get_settings)) -> Assistant:
    memory_db = MemoryDatabase(settings.memory_db_path)
    memory_db.init()
    return Assistant(settings, memory_db)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, assistant: Assistant = Depends(get_assistant)) -> ChatResponse:
    try:
        response = await assistant.chat(
            message=request.message,
            provider_name=request.provider,
            conversation_id=request.conversation_id,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ChatResponse(
        conversation_id=response.conversation_id,
        provider=response.provider,
        message=response.message,
        recalled=response.recalled,
        metadata=response.metadata,
    )
