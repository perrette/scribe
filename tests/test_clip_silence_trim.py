"""Clip-mode silence capping (clip_max_silence).

In Clip mode the recording accumulates into session.audio_buffer and is
transcribed once at finalize(). Silent pauses are diverted to
session.silence_buffer and only their tail (clip_max_silence seconds) is
re-added when speech resumes, so dead air never inflates the audio sent
to (and billed by) remote backends. Mirrors the FakeBackend/SimpleNamespace
harness from test_pseudo_streaming.py.
"""
import time
from types import SimpleNamespace

import numpy as np

from scribe.models import AbstractTranscriber

SR = 16000


class FakeBackend(AbstractTranscriber):
    name = "fake"
    backend = "fake"

    def __init__(self, *args, vad_mode="db", pseudo_streaming=False, **kwargs):
        super().__init__(*args, vad_mode=vad_mode,
                         pseudo_streaming=pseudo_streaming, **kwargs)

    def transcribe_audio(self, audio_bytes):
        return {"text": "fake"}

    def finalize(self):
        return {"text": "fake"}


def make_session():
    now = time.time()
    sess = SimpleNamespace(
        audio_buffer=b'',
        silence_buffer=b'',
        trimmed_silence_bytes=0,
        silence_intervals=[],
        silence_start_ms=None,
        start_time=now,
        last_sound_time=now,
        waiting=False,
    )
    sess.get_elapsed = lambda: time.time() - sess.start_time
    sess.log = lambda msg: None
    return sess


def make_backend(session, **kwargs):
    backend = FakeBackend(model=None, samplerate=SR, **kwargs)
    backend.session = session
    return backend


def silent_chunk(seconds=0.1):
    return np.zeros(int(seconds * SR), dtype=np.int16).tobytes()


def loud_chunk(seconds=0.1, amplitude=16000):
    return (np.ones(int(seconds * SR), dtype=np.int16) * amplitude).tobytes()


def secs(buf):
    return len(buf) / (SR * 2)


def test_long_pause_capped_to_max_silence():
    sess = make_session()
    backend = make_backend(sess, clip_max_silence=2.0)
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    for _ in range(100):  # 10 s pause in 100 ms blocks
        backend.transcribe_realtime_audio(silent_chunk(0.1))
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    # 1 s speech + <= 2 s retained silence + 1 s speech
    assert secs(sess.audio_buffer) == 4.0
    assert sess.trimmed_silence_bytes == int(8.0 * SR) * 2


def test_short_pause_kept_verbatim():
    sess = make_session()
    backend = make_backend(sess, clip_max_silence=2.0)
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    for _ in range(10):  # 1 s pause, under the cap
        backend.transcribe_realtime_audio(silent_chunk(0.1))
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    assert secs(sess.audio_buffer) == 3.0
    assert sess.trimmed_silence_bytes == 0


def test_trailing_silence_dropped():
    sess = make_session()
    backend = make_backend(sess, clip_max_silence=2.0)
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    for _ in range(50):  # 5 s of trailing silence, never followed by speech
        backend.transcribe_realtime_audio(silent_chunk(0.1))
    # finalize() reads audio_buffer only — the pause stays out of it.
    assert secs(sess.audio_buffer) == 1.0


def test_zero_disables_trimming():
    sess = make_session()
    backend = make_backend(sess, clip_max_silence=0)
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    for _ in range(50):
        backend.transcribe_realtime_audio(silent_chunk(0.1))
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    assert secs(sess.audio_buffer) == 7.0
    assert sess.trimmed_silence_bytes == 0


def test_partial_reports_trimmed_seconds():
    sess = make_session()
    backend = make_backend(sess, clip_max_silence=2.0)
    backend.transcribe_realtime_audio(loud_chunk(1.0))
    for _ in range(50):
        backend.transcribe_realtime_audio(silent_chunk(0.1))
    result = backend.transcribe_realtime_audio(loud_chunk(1.0))
    assert "trimmed 3.0s silence" in result["partial"]
