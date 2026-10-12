from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from core.config import Settings, get_settings
from voice.stt import TranscriptionError, transcribe_audio


router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe_voice(file: UploadFile = File(...), settings: Settings = Depends(get_settings)):
    import asyncio
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    data = await file.read(10_000_001)
    if len(data) > 10_000_000:
        raise HTTPException(413, "Audio upload exceeds 10 MB")
    with tempfile.TemporaryDirectory() as directory:
        audio_path = Path(directory) / ("audio" + suffix)
        audio_path.write_bytes(data)
        try:
            result = await asyncio.to_thread(transcribe_audio, str(audio_path), provider=settings.stt_provider, model_name=settings.stt_model)
        except TranscriptionError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"text": result.text, "provider": result.provider, "model": result.model}
