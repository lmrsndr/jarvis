from __future__ import annotations

import sys
from pathlib import Path

import pytest

from voice.stt import TranscriptionError, transcribe_audio


def test_local_stt_missing_dependency_has_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio_path = tmp_path / "audio.webm"
    audio_path.write_bytes(b"not real audio")
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    with pytest.raises(TranscriptionError, match="faster-whisper"):
        transcribe_audio(str(audio_path), provider="local", model_name="base")


def test_non_local_stt_provider_is_refused(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.webm"
    audio_path.write_bytes(b"not real audio")

    with pytest.raises(TranscriptionError, match="Only local"):
        transcribe_audio(str(audio_path), provider="openai", model_name="base")
