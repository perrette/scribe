"""FUTO ACFT Whisper backend (whisper.cpp via pywhispercpp).

Uses FUTO's audio-context-finetuned ggml models from
https://voiceinput.futo.org/. The ACFT training lets the encoder run on the
actual audio length instead of always padding to 30 s, giving a large
speedup on short dictations (scribe's typical workload). For audio ≥ 30 s
whisper.cpp falls back to its built-in 30 s window iteration, so there is
no regression on long recordings — only no ACFT win.

Models exposed match the `whisper` backend naming (tiny/base/small + .en
variants). FUTO has not released medium / large / turbo ACFT weights, so
those sizes stay on the existing `whisper` backend.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import ClassVar

import numpy as np

from scribe.models import AbstractTranscriber


# Whisper hallucinates sound-effect annotations like "(music)", "[Applause]"
# on near-silence, and occasionally emits IPA-modifier-letter garbage
# (U+02B0–02FF) or U+FFFD when the audio is unintelligible. Two filters:
#   - WHOLE_RE: chunk is one such artifact end-to-end → drop.
#   - INLINE_RE: artifact embedded mid-text ("Bonjour (typing) ça va") →
#     substitute out. Restricted to lowercase ASCII + spaces inside the
#     brackets so legitimate French parentheticals (accents) and proper
#     nouns (uppercase) are preserved. pywhispercpp 1.4.1 advertises
#     `suppress_non_speech_tokens` in its schema but the C struct doesn't
#     expose it, so this lives at the text layer.
_NON_SPEECH_WHOLE_RE = re.compile(r"^\s*[(\[*][^()\[\]*]{1,60}[)\]*]\s*[.!?]?\s*$")
# Allow any case ([Breathing], [KNOCKING], [Door opens], (footsteps)) and
# consume any trailing punctuation so adjacent text doesn't end up with
# stray commas. Substitute with a space (not "") so adjacent words don't
# collide when the noise token has no surrounding whitespace
# ("[door][door]" or "word(typing)word"); a follow-up \s+ collapse cleans
# up any doubles.
_NON_SPEECH_INLINE_RE = re.compile(r"[(\[][A-Za-z][A-Za-z\s\-]{0,30}[)\]][.,!?:;]?")
_WHITESPACE_RE = re.compile(r"\s+")
_PHONETIC_RE = re.compile(r"[ʰ-˿�]")


_FUTO_BASE_URL = "https://voiceinput.futo.org/VoiceInput/"

# Map user-visible model name → ggml filename on FUTO's CDN. FUTO publishes
# only tiny/base/small (+ .en variants). The DeadBranches community q8_0 of
# large-v3-turbo was tried briefly but its large-v3 encoder is incompatible
# with the audio_ctx-shrinkage that's the whole point of this backend
# (Progress: 1612% / CJK garbage on short clips), so we stick to the FUTO
# set where ACFT works as advertised.
_FUTO_MODELS: dict[str, str] = {
    "tiny":     "tiny_acft_q8_0.bin",
    "tiny.en":  "tiny_en_acft_q8_0.bin",
    "base":     "base_acft_q8_0.bin",
    "base.en":  "base_en_acft_q8_0.bin",
    "small":    "small_acft_q8_0.bin",
    "small.en": "small_en_acft_q8_0.bin",
}

# Whisper encoder produces 1500 audio_ctx tokens for the full 30 s window
# (50 per second after the 2× conv subsampling of 100 mel frames/s).
_AUDIO_CTX_PER_SECOND = 50
_AUDIO_CTX_MAX = 1500
_AUDIO_CTX_MIN = 8  # whisper.cpp asserts a minimum; very short utterances


def _default_download_folder() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.environ.get("HOME", os.path.expanduser("~")), ".cache"
    )
    return Path(base) / "whisper-futo"


def _model_path(model_name: str, download_folder: str | os.PathLike | None) -> Path:
    if model_name not in _FUTO_MODELS:
        raise ValueError(
            f"Unknown whisper-futo model '{model_name}'. "
            f"Available: {', '.join(_FUTO_MODELS)}"
        )
    folder = Path(download_folder) if download_folder else _default_download_folder()
    return folder / _FUTO_MODELS[model_name]


def _ensure_model(model_name: str, path: Path) -> None:
    """Download the ggml file from voiceinput.futo.org if it isn't on disk yet."""
    if path.exists():
        return
    import requests
    import tqdm

    url = _FUTO_BASE_URL + _FUTO_MODELS[model_name]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    print(f"Downloading {url} -> {path}")
    resp = requests.get(url, stream=True)
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"FUTO model download failed: HTTP {resp.status_code}")
    total = int(resp.headers.get("content-length", 0))
    with open(tmp, "wb") as f, tqdm.tqdm(total=total, unit="iB", unit_scale=True) as bar:
        for chunk in resp.iter_content(1024 * 64):
            if not chunk:
                continue
            f.write(chunk)
            bar.update(len(chunk))
    tmp.rename(path)


class WhisperFutoTranscriber(AbstractTranscriber):
    name = "whisper-futo"
    backend = "whisper-futo"
    default_model: str | None = "small"
    is_local: ClassVar[bool] = True

    def __init__(self, model_name, language=None, model=None, model_kwargs={},
                 download_folder=None, prompt=None, dry_run=False, **kwargs):
        if model is None and not dry_run:
            from pywhispercpp.model import Model
            path = _model_path(model_name, download_folder)
            _ensure_model(model_name, path)
            # pywhispercpp 1.4.1 raises "cannot create std::vector larger than
            # max_size" if n_threads is 0; pass an explicit count.
            n_threads = model_kwargs.get("n_threads") or os.cpu_count() or 4
            init_kwargs = {k: v for k, v in model_kwargs.items() if k != "n_threads"}
            model = Model(str(path), n_threads=n_threads, **init_kwargs)
        super().__init__(model, model_name, language, model_kwargs=model_kwargs,
                         dry_run=dry_run, **kwargs)
        self._prompt = prompt

    def transcribe_audio(self, audio_bytes):
        self.log("\nTranscribing")
        if self.dry_run:
            # Short-circuit before the pywhispercpp call.
            self.dry_run_hits += 1
            text = "[dry-run transcript]"
            self.update_streaming_context(text)
            return {"text": (text + " ") if self.pseudo_streaming else text}
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        duration_s = len(audio) / self.samplerate

        # ACFT shortcut: shrink the encoder window to the actual audio
        # length. This is the whole point of the FUTO backend — without it,
        # a 2 s clip runs against the full 30 s window and inference is
        # 5-10× slower. Safe for the FUTO ACFT set (tiny/base/small +
        # .en) which was trained to preserve quality at short audio_ctx.
        # pywhispercpp wants "" (not "auto") to request auto-detect.
        kwargs = {
            "language": self.language or "",
            "audio_ctx": min(_AUDIO_CTX_MAX,
                             max(_AUDIO_CTX_MIN,
                                 math.ceil(duration_s * _AUDIO_CTX_PER_SECOND))),
        }
        prompt = self.compose_prompt(self._prompt)
        if prompt:
            kwargs["initial_prompt"] = prompt
        # Streaming-only safety nets. max_tokens caps decoder repetition
        # loops on short silence-split chunks; the non-speech filter
        # below drops "(music)"-style hallucinations from those same
        # tiny chunks. Both can clip real speech in batch where the
        # recording is a single longer utterance.
        if self.pseudo_streaming:
            kwargs["max_tokens"] = max(12, int(duration_s * 12))
        self.debug_log_request(audio_bytes, model=self.model_name,
                               language=kwargs.get("language"),
                               prompt=kwargs.get("initial_prompt"),
                               audio_ctx=kwargs.get("audio_ctx"),
                               max_tokens=kwargs.get("max_tokens"))
        segments = self.model.transcribe(audio, **kwargs)
        text = "".join(s.text for s in segments)
        if self.pseudo_streaming:
            # Inline pass first: catches concatenated noise tokens like
            # "[door opens][door closes]" and mid-sentence "(typing)"
            # inserts. Replace with " " then collapse to avoid gluing
            # adjacent words. Whole-chunk fallback catches artifacts the
            # inline pattern misses (internal punctuation inside brackets).
            text = _NON_SPEECH_INLINE_RE.sub(" ", text)
            text = _WHITESPACE_RE.sub(" ", text).strip()
            if _NON_SPEECH_WHOLE_RE.match(text):
                text = ""
        else:
            text = text.strip()
        # Phonetic garbage (IPA modifier letters, U+FFFD) is always a
        # decode failure — drop in both modes.
        if _PHONETIC_RE.search(text):
            text = ""
        # Carry the cleaned text forward as cross-chunk context. Done
        # post-filter so hallucination/phonetic-garbage chunks (now "")
        # don't poison the next chunk's prompt.
        self.update_streaming_context(text)
        # Trailing space lets pseudo-streaming chunks concatenate cleanly
        # (vosk convention). Harmless in batch mode — downstream strips.
        if text:
            text += " "
        return {"text": text}

    def finalize(self):
        if len(self.session.audio_buffer) == 0:
            return {"text": ""}
        result = self.transcribe_audio(self.session.audio_buffer)
        self.session.reset()
        return result


def _probe_whisper_futo() -> tuple[bool, str | None]:
    import importlib.util
    if importlib.util.find_spec("pywhispercpp") is None:
        return False, "pywhispercpp not installed (pip install pywhispercpp)"
    return True, None
