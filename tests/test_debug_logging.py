"""Tests for the ``--debug`` request-logging path.

``AbstractTranscriber.debug_log_request`` is a thin helper that each
backend calls just before its SDK / network boundary so the user can
see exactly which model / language / prompt is being sent. The flag is
threaded through ``app.get_transcriber`` → ``_build_backend_kwargs`` →
each backend's ``__init__`` so the CLI ``--debug`` switch flips it on.

These tests cover:

- ``debug_log_request`` is a no-op when ``self.debug`` is False.
- When True it prints a single ``[req backend=... ...]`` line on stdout,
  including the audio duration when ``audio_bytes`` is provided.
- Long prompt strings are truncated at ~200 chars with an ellipsis so
  the log line stays scannable.
- End-to-end: building a transcriber with ``debug=True`` and driving
  ``transcribe_audio`` past the SDK boundary actually emits the line.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest

from scribe.app import get_transcriber
from scribe.models import AbstractTranscriber


SR = 16000


# ── unit: debug_log_request ──────────────────────────────────────────────


class _Fake(AbstractTranscriber):
    """Minimal AbstractTranscriber subclass for direct-method tests.

    We don't need a real model/session — only the bits ``debug_log_request``
    touches (``backend``, ``samplerate``, ``debug``, ``log``). Bypass
    ``__init__`` (which pulls in VAD / silence-gate plumbing we don't
    care about here) and set the attrs by hand.
    """
    backend = "fake"

    def __init__(self, debug):
        # Skip AbstractTranscriber.__init__ entirely — we only need a few
        # attributes for debug_log_request and self.log.
        self.debug = debug
        self.samplerate = SR
        self.session = None


def test_debug_log_request_noop_when_disabled(capsys):
    t = _Fake(debug=False)
    t.debug_log_request(b"\x00" * 1600, model="whisper-tiny", prompt="hi")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_debug_log_request_prints_when_enabled(capsys):
    t = _Fake(debug=True)
    # 16000 samples × 2 bytes/sample @ 16 kHz = 1.0 s
    audio = b"\x00" * (SR * 2)
    t.debug_log_request(audio, model="whisper-tiny", language="en",
                        prompt="Tierney, Comet.")
    out = capsys.readouterr().out
    assert "[req " in out
    assert "backend=fake" in out
    assert "model='whisper-tiny'" in out
    assert "language='en'" in out
    assert "prompt='Tierney, Comet.'" in out
    assert "audio_s=1.00" in out


def test_debug_log_request_omits_audio_when_not_passed(capsys):
    t = _Fake(debug=True)
    t.debug_log_request(model="x", prompt="y")
    out = capsys.readouterr().out
    assert "audio_s=" not in out
    assert "model='x'" in out
    assert "prompt='y'" in out


def test_debug_log_request_truncates_long_strings(capsys):
    t = _Fake(debug=True)
    long_prompt = "x" * 500
    t.debug_log_request(model="m", prompt=long_prompt)
    out = capsys.readouterr().out
    # 197 chars + "..." = 200-char truncation. Surrounding quotes from repr.
    assert "..." in out
    # The full 500-char string must NOT appear verbatim.
    assert long_prompt not in out
    # The truncated head should be present.
    assert "x" * 100 in out


# ── plumbing: --debug threads through get_transcriber ────────────────────


def test_debug_flag_threads_through_get_transcriber():
    """``--debug`` should land on the transcriber as ``self.debug``.

    Uses the openai backend with ``dry_run=True`` so we don't need
    network or an API key — same trick as ``test_backend_matrix``.
    """
    os.environ.setdefault("OPENAI_API_KEY", "dummy")
    transcriber = get_transcriber(
        backend="openai", model="gpt-4o-mini-transcribe",
        interactive=False,
        samplerate=SR,
        dry_run=True,
        debug=True,
    )
    assert transcriber.debug is True


def test_debug_flag_defaults_false():
    os.environ.setdefault("OPENAI_API_KEY", "dummy")
    transcriber = get_transcriber(
        backend="openai", model="gpt-4o-mini-transcribe",
        interactive=False,
        samplerate=SR,
        dry_run=True,
    )
    assert transcriber.debug is False


# ── end-to-end: openai backend emits the req line ────────────────────────


class _FakeTranscriptions:
    """Stand-in for ``openai.OpenAI().audio.transcriptions``."""
    def __init__(self):
        self.calls = []

    def create(self, model, file, **extra):
        self.calls.append({"model": model, "extra": extra})
        return SimpleNamespace(text="ok")


class _FakeOpenAIModel:
    def __init__(self):
        self.audio = SimpleNamespace(transcriptions=_FakeTranscriptions())


def test_openai_backend_emits_request_log(capsys, monkeypatch):
    """End-to-end: with ``debug=True`` and the SDK boundary mocked, the
    openai backend's ``transcribe_audio`` should print a ``[req ...]``
    line that reports the model and the composed prompt.

    ``soundfile`` may not be installed in every test env (it's only used
    by the openai/groq cloud path), so we stub it out via monkeypatch
    before calling ``transcribe_audio``.
    """
    # Stub `soundfile` so the openai backend's `import soundfile as sf`
    # succeeds without the real package; sf.write is the only attr it
    # touches and a no-op writer is enough for the boundary.
    import sys
    fake_sf = SimpleNamespace(write=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "soundfile", fake_sf)

    os.environ.setdefault("OPENAI_API_KEY", "dummy")
    fake_client = _FakeOpenAIModel()
    transcriber = get_transcriber(
        backend="openai", model="gpt-4o-mini-transcribe",
        interactive=False,
        samplerate=SR,
        prompt="Tierney, Comet.",
        dry_run=False,
        debug=True,
    )
    # Swap in the fake client (get_transcriber already built a real
    # openai.OpenAI() instance — replace it before calling).
    transcriber.model = fake_client

    # ~0.5 s of int16 silence is plenty for the boundary to fire.
    audio_bytes = (np.zeros(SR // 2, dtype=np.int16)).tobytes()
    result = transcriber.transcribe_audio(audio_bytes)
    assert result["text"] == "ok"

    out = capsys.readouterr().out
    assert "[req " in out
    assert "backend=openai" in out
    assert "model='gpt-4o-mini-transcribe'" in out
    # Our --prompt value is at the front; the user's environment may have
    # a default words file that gets appended after, so substring-check.
    assert "Tierney, Comet." in out
    assert "audio_s=0.50" in out
