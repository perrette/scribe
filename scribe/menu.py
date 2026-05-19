from pathlib import Path
import tomllib

from scribe.backends import BACKENDS

_VENDOR_PREFIX = {
    "openai": "OpenAI",
    "groq": "Groq",
    "whisper": "Whisper",
    "vosk": "Vosk",
}

_vosk_model_to_lang: dict[str, str] | None = None


def _vosk_language_for_model(model_id: str) -> str | None:
    global _vosk_model_to_lang
    if _vosk_model_to_lang is None:
        toml_path = Path(__file__).parent / "models.toml"
        with open(toml_path, "rb") as f:
            config = tomllib.load(f)
        _vosk_model_to_lang = {}
        for lang_code, entry in config.get("vosk", {}).items():
            mid = entry.get("model")
            if mid:
                lang_name = config.get("_meta", {}).get(lang_code, {}).get("language", lang_code)
                _vosk_model_to_lang[mid] = lang_name
    return _vosk_model_to_lang.get(model_id)


def format_model_label(backend_name: str, model_id: str) -> str:
    vendor = _VENDOR_PREFIX.get(backend_name, backend_name.capitalize())
    backend_cls = BACKENDS.get(backend_name)
    is_local = backend_cls.is_local if backend_cls is not None else False

    if backend_name == "vosk":
        lang = _vosk_language_for_model(model_id)
        display = lang if lang is not None else model_id
        return f"{vendor} {display} (local, live partials)"

    qualifier = ""
    if backend_name == "openai" and model_id == "whisper-1":
        qualifier = " (deprecated)"
    elif is_local:
        qualifier = " (local)"

    return f"{vendor} {model_id}{qualifier}"
