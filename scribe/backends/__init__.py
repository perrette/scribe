"""Scribe STT backend registry.

Each backend module subclasses `scribe.models.AbstractTranscriber` (itself an
`STTBackend`) and registers its class via `desktop_ai_core.providers.register_stt`
at import time. The names `BACKENDS`, `get_transcriber`, `available_backends`,
and `probe_backend` are thin wrappers over the shared registry — `BACKENDS` is
the registry dict itself, so `BACKENDS['vosk'] is VoskTranscriber` after import.
"""

from desktop_ai_core.providers import register_stt, get_stt, available_stt, probe_stt
from desktop_ai_core.providers.registry import _STT_REGISTRY

from scribe.backends.vosk import VoskTranscriber, _probe_vosk
from scribe.backends.whisper import WhisperTranscriber, _probe_whisper
from scribe.backends.openai_api import OpenaiAPITranscriber, _probe_openai

register_stt("vosk", VoskTranscriber, probe=_probe_vosk)
register_stt("whisper", WhisperTranscriber, probe=_probe_whisper)
register_stt("openaiapi", OpenaiAPITranscriber, probe=_probe_openai)

BACKENDS = _STT_REGISTRY


def get_transcriber(backend: str, **kwargs):
    """Thin wrapper over `desktop_ai_core.providers.get_stt`."""
    return get_stt(backend, **kwargs)


def available_backends() -> list[str]:
    return available_stt()


def probe_backend(name: str) -> tuple[bool, str | None]:
    return probe_stt(name)


__all__ = [
    "BACKENDS",
    "get_transcriber",
    "available_backends",
    "probe_backend",
    "VoskTranscriber",
    "WhisperTranscriber",
    "OpenaiAPITranscriber",
]
