from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from core.config import Settings, get_settings
from voice.stt import TranscriptionError, transcribe_audio


router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe_voice(file: UploadFile = File(...), settings: Settings = Depends(get_settings)):
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as temp_file:
        temp_file.write(await file.read())
        temp_file.flush()
        try:
            result = transcribe_audio(temp_file.name, provider=settings.stt_provider, model_name=settings.stt_model)
        except TranscriptionError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"text": result.text, "provider": result.provider, "model": result.model}
