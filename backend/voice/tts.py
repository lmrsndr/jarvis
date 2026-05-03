from __future__ import annotations


class TextToSpeechError(RuntimeError):
    pass


def synthesize_speech(_text: str, _output_path: str) -> None:
    raise TextToSpeechError("Text-to-speech is a placeholder. No TTS provider is enabled yet.")
