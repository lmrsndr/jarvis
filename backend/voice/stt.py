from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from threading import Lock


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str


@lru_cache(maxsize=2)
def _model(name):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionError(
            "Local speech-to-text failed: install faster-whisper from backend/requirements-voice.txt."
        ) from exc
    return WhisperModel(name, device="cpu", compute_type="int8")


_lock = Lock()


class LocalSTTProvider:
    def __init__(self, model_name="base"):
        self.model_name = model_name

    def transcribe(self, path):
        if not Path(path).exists():
            raise TranscriptionError(f"Audio file not found: {path}")
        try:
            with _lock:
                segments, _ = _model(self.model_name).transcribe(path)
                text = " ".join(s.text.strip() for s in segments if s.text.strip())
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(
                "Local speech-to-text failed: " + str(exc)
            ) from exc
        return TranscriptionResult(text, "local", self.model_name)


def transcribe_audio(path, provider="local", model_name="base"):
    if provider != "local":
        raise TranscriptionError("Only local speech-to-text is supported by default.")
    return LocalSTTProvider(model_name).transcribe(path)
