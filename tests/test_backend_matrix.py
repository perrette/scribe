"""Integration smoke-test matrix.

Drives every (backend, mode) cell through the recording pipeline up to the
request boundary, verifying that ``RecordingSession.start_recording`` does
not crash and that the dry-run intercept is reached. Catches the class of
stale-attribute regression that ``dc9fe69`` fixed (e.g. session.py once
referred to ``backend.silence_duration`` after the field was renamed).

Each cell:

1. Builds the transcriber via ``scribe.app.get_transcriber`` with
   ``dry_run=True``. Dry-run stubs the model load + network call so the
   matrix is runnable on machines without every model on disk and without
   GROQ_API_KEY / OPENAI_API_KEY set.
2. Drives a ``RecordingSession`` against a ``FakeMicrophone`` that feeds a
   short canned PCM stream (alternating speech + silence so the silence-cut
   path triggers at least once for batch backends in --stream mode).
3. Asserts no exception is raised AND, where the backend exposes a flag,
   that the dry-run boundary fired at least once.

Cells whose backend dependency is not installed (vosk, faster-whisper,
pywhispercpp) are marked ``pytest.skip`` — the dry-run flag still threads
through ``get_transcriber`` so the plumbing test runs unconditionally
above.
"""
from __future__ import annotations

import os
import queue
import threading
import time

import numpy as np
import pytest

from scribe.app import get_transcriber
from scribe.backends import probe_backend
from scribe.session import RecordingSession


SR = 16000


# Matrix definition --------------------------------------------------------

BACKEND_CELLS = [
    # (backend, model, mode_label, pseudo_streaming)
    # mode_label: "clip" (batch-end transcription) | "stream" (chunked)
    ("vosk",         "vosk-model-small-en-us-0.15", "clip",   False),
    ("vosk",         "vosk-model-small-en-us-0.15", "stream", True),
    ("whisper",      "tiny",                        "clip",   False),
    ("whisper",      "tiny",                        "stream", True),
    ("whisper-futo", "tiny",                        "clip",   False),
    ("whisper-futo", "tiny",                        "stream", True),
    ("groq",         "whisper-large-v3-turbo",      "clip",   False),
    ("groq",         "whisper-large-v3-turbo",      "stream", True),
    ("openai",       "gpt-4o-mini-transcribe",      "clip",   False),
    ("openai",       "gpt-4o-mini-transcribe",      "stream", True),
    ("openai",       "gpt-realtime-whisper",        "clip",   False),
    ("openai",       "gpt-realtime-whisper",        "stream", True),
]


# Fake microphone ----------------------------------------------------------

class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeMicrophone:
    """Drop-in replacement for scribe.audio.Microphone.

    Pre-loads the queue with a deterministic alternating sequence of loud
    + silent PCM chunks; ``open_stream()`` is a no-op context manager so
    we never touch sounddevice.
    """

    def __init__(self, chunks: list[bytes]):
        self.q: queue.Queue = queue.Queue()
        for chunk in chunks:
            self.q.put(chunk)

    def open_stream(self):
        return _FakeStream()


def _loud(samples: int = 1600, amplitude: int = 16000) -> bytes:
    return (np.ones(samples, dtype=np.int16) * amplitude).tobytes()


def _silent(samples: int = 1600) -> bytes:
    return np.zeros(samples, dtype=np.int16).tobytes()


def _make_audio_program(pseudo_streaming: bool) -> list[bytes]:
    """Build a short alternating speech/silence script.

    In stream mode we feed enough speech + a long pause to land at least
    one silence-cut for batch backends. In clip mode we just need a few
    chunks so finalize() has something to chew on.
    """
    if pseudo_streaming:
        # 2s loud (above stream_chunk_min) then 1s silent (above
        # stream_chunk_silence_break=0.6) → silence-cut fires.
        prog: list[bytes] = []
        # 2 s of loud audio in 100 ms chunks
        prog += [_loud(samples=SR // 10) for _ in range(20)]
        # 1 s of silence in 100 ms chunks
        prog += [_silent(samples=SR // 10) for _ in range(10)]
        # 0.5 s more loud (post-cut, exercises the resumption path)
        prog += [_loud(samples=SR // 10) for _ in range(5)]
        return prog
    # Clip mode: ~1 s of loud audio is enough; finalize() will run on
    # generator close.
    return [_loud(samples=SR // 10) for _ in range(10)]


# Probe helpers ------------------------------------------------------------

def _skip_if_backend_unavailable(backend: str):
    """Probe the backend's package + creds — but only skip if the
    dry-run path can't construct the transcriber without the package.

    The whole point of ``dry_run=True`` is that every backend's
    ``__init__`` lazily imports its heavy dependency (faster-whisper,
    pywhispercpp, vosk, openai SDK) behind ``if model is None and not
    dry_run``. So in practice every cell is runnable here regardless
    of ``probe_backend``. The probe result is surfaced as a warning
    line in the captured output so a CI matrix can still flag a
    machine where the dependency is missing.

    Cloud backends (openai, groq) don't need real keys under dry-run.
    """
    if backend in ("openai", "groq"):
        return
    ok, reason = probe_backend(backend)
    if not ok:
        # No skip — dry-run lets the cell run without the package.
        # Print so the reason is visible in the test capture.
        print(f"[dry-run note] {backend} package not installed: {reason}")


# Boundary detection ------------------------------------------------------

def _intercept_fired(backend_obj) -> bool:
    """Did the dry-run short-circuit actually fire at least once?

    ``dry_run_hits`` lives on ``AbstractTranscriber`` and is bumped by
    every backend's dry-run branch (whisper / whisper-futo /
    openai_api / vosk / openai_realtime). A non-zero count means the
    request boundary was reached.
    """
    return getattr(backend_obj, "dry_run_hits", 0) > 0


# Drive a recording session -----------------------------------------------

def _drive_session(session: RecordingSession, micro: FakeMicrophone,
                   time_budget_s: float = 3.0):
    """Run ``session.start_recording(micro)`` to completion on a worker
    thread; signal interrupt once the canned audio program has been
    consumed (or the time budget elapses).

    Threading is the cleanest way to drive this: the session loop owns
    its own ``time.sleep(0.1)`` between queue drains, and some backends
    (openai_realtime with default ``_coalesce_deltas=True``) yield
    nothing on the first chunk — a single-threaded ``next(gen)`` would
    block until the flush interval elapses. Letting it run on its own
    thread + signalling interrupt sidesteps that entirely.

    Returns the list of yielded events. The generator's ``finally``
    block runs as part of normal exit, calling ``backend.finalize()``
    and ``close_session()`` so the request boundary is exercised.
    """
    results: list[dict] = []

    def _consume():
        try:
            for event in session.start_recording(micro):
                results.append(event)
        except Exception as exc:  # pragma: no cover — re-raised below
            results.append({"_test_error": repr(exc)})

    thread = threading.Thread(target=_consume, daemon=True)
    thread.start()

    # Wait for the canned audio to drain, then ask the loop to exit.
    deadline = time.time() + time_budget_s
    while time.time() < deadline:
        if micro.q.empty():
            break
        time.sleep(0.05)
    session.interrupt = True

    thread.join(timeout=time_budget_s)
    if thread.is_alive():
        pytest.fail("session thread did not exit within time budget")

    # Surface any internal exception (the session normally swallows them
    # to keep the recording loop alive; in the test we want them loud).
    for event in results:
        if "_test_error" in event:
            pytest.fail(f"session loop raised: {event['_test_error']}")
    return results


# Parametrised matrix -----------------------------------------------------

@pytest.mark.parametrize("backend,model,mode_label,pseudo_streaming", BACKEND_CELLS,
                         ids=[f"{b}-{m}-{mode}" for b, m, mode, _ in BACKEND_CELLS])
def test_backend_matrix_dry_run(backend, model, mode_label, pseudo_streaming):
    """For each (backend, model, mode) cell: drive a recording end-to-end
    against the dry-run boundary and assert no exception + boundary hit."""
    _skip_if_backend_unavailable(backend)

    # Force a deterministic VAD that doesn't need silero state machinery
    # across the cell variants. silero is a separate code path; the
    # silence-cut logic this test cares about is the dB one (the
    # AbstractTranscriber.transcribe_realtime_audio body is the same).
    transcriber = get_transcriber(
        backend=backend, model=model,
        interactive=False,
        samplerate=SR,
        clip_timeout=30.0,
        silence_db=-40.0,
        stream_chunk_silence_break=0.6,
        stream_chunk_max=10.0,
        stream_chunk_min=1.5,
        pseudo_streaming=pseudo_streaming,
        vad_mode="db",
        dry_run=True,
    )
    # Sanity: dry_run actually threaded through.
    assert getattr(transcriber, "dry_run", False) is True

    session = RecordingSession(backend=transcriber)
    micro = FakeMicrophone(_make_audio_program(pseudo_streaming))

    # Drive the session. Any exception from the pipeline propagates.
    results = _drive_session(session, micro)

    # At least the finalize() pass should yield something (the final
    # transcript dict, possibly with empty text for the openai_realtime
    # path if no audio was sent before close — that path is exercised
    # but doesn't enqueue deltas without a real WS).
    assert isinstance(results, list)

    # Boundary fired — strongest signal across all cells. For batch
    # backends in clip mode the boundary fires inside finalize() (which
    # the generator's finally block calls), so we check after
    # _drive_session returns.
    assert _intercept_fired(transcriber), (
        f"{backend}/{model}/{mode_label}: dry-run boundary not reached"
    )


# Plumbing test — runs unconditionally ------------------------------------

@pytest.mark.parametrize("backend,model", [
    ("openai", "gpt-4o-mini-transcribe"),
    ("openai", "gpt-realtime-whisper"),
    ("groq",   "whisper-large-v3-turbo"),
])
def test_dry_run_flag_threads_through(backend, model):
    """The --dry-run flag should land on the transcriber as
    ``self.dry_run`` regardless of backend. Smoke-tests the plumbing
    independently of whether we actually drive a session."""
    # Groq is gated on GROQ_API_KEY but dry-run skips the SDK init, so
    # we don't need a real key. Forge a dummy so _probe_groq's gate (used
    # by get_default_backend, not here) doesn't matter.
    os.environ.setdefault("GROQ_API_KEY", "dummy")
    transcriber = get_transcriber(
        backend=backend, model=model,
        interactive=False,
        samplerate=SR,
        dry_run=True,
    )
    assert transcriber.dry_run is True


# Stale-attribute regression guard ---------------------------------------

def test_session_does_not_reference_silence_duration():
    """The dc9fe69 fix dropped ``backend.silence_duration``; assert the
    rename didn't leak back. Same pattern for ``streaming_window`` and
    the legacy ``duration`` attribute on the transcriber."""
    import scribe.session as session_mod
    src = open(session_mod.__file__).read()
    for stale in ("backend.silence_duration", "self.backend.silence_duration",
                  "backend.streaming_window", "self.backend.streaming_window"):
        assert stale not in src, f"stale attr ref leaked back: {stale}"
