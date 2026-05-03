from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str


class LocalSTTProvider:
    def __init__(self, model_name: str = "base") -> None:
        self.model_name = model_name

    def transcribe(self, path: str) -> TranscriptionResult:
        audio_path = Path(path)
        if not audio_path.exists():
            raise TranscriptionError(f"Audio file not found: {audio_path}")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "Local speech-to-text requires faster-whisper. Install it with "
                "`main/bin/python -m pip install faster-whisper` and set JARVIS_STT_PROVIDER=local."
            ) from exc

        try:
            model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            segments, _info = model.transcribe(str(audio_path))
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        except Exception as exc:
            raise TranscriptionError(f"Local speech-to-text failed: {exc}") from exc
        return TranscriptionResult(text=text, provider="local", model=self.model_name)


def transcribe_audio(path: str, provider: str = "local", model_name: str = "base") -> TranscriptionResult:
    if provider != "local":
        raise TranscriptionError("Only local speech-to-text is supported by default.")
    return LocalSTTProvider(model_name).transcribe(path)
