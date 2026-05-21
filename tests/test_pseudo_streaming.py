"""Unit tests for pseudo-streaming pieces in scribe.models and the
is_streaming gate in scribe.app.

Covers the recent behaviour changes:
- silence-cut fires on any detected silence (was gated by elapsed >= streaming_window)
- silence_buffer capped at max(5s, silence_duration)
- is_streaming reflects pseudo_streaming on the instance, not just the class
"""
import os
import time
from types import SimpleNamespace

import numpy as np
import pytest

from scribe.models import AbstractTranscriber, SilenceDetected, is_silent


SR = 16000  # 16 kHz, matches scribe defaults


class FakeBackend(AbstractTranscriber):
    """Minimal AbstractTranscriber subclass: drives transcribe_realtime_audio
    without needing a real STT model."""
    name = "fake"
    backend = "fake"

    def transcribe_audio(self, audio_bytes):
        return {"text": "fake"}

    def finalize(self):
        return {"text": "fake"}


def make_session(*, audio_buffer=b'', silence_buffer=b'',
                 start_time=None, last_sound_time=None):
    now = time.time()
    sess = SimpleNamespace(
        audio_buffer=audio_buffer,
        silence_buffer=silence_buffer,
        start_time=start_time if start_time is not None else now,
        last_sound_time=last_sound_time if last_sound_time is not None else now,
        waiting=False,
    )
    # RecordingSession exposes this; the non-pseudo branch calls it.
    sess.get_elapsed = lambda: time.time() - sess.start_time
    return sess


def silent_chunk(samples=1600):
    """100ms of pure silence at 16 kHz (calculate_decibels returns -inf)."""
    return np.zeros(samples, dtype=np.int16).tobytes()


def loud_chunk(samples=1600, amplitude=16000):
    """100ms of ~-6 dB constant signal at 16 kHz."""
    return (np.ones(samples, dtype=np.int16) * amplitude).tobytes()


def medium_chunk(samples=1600, amplitude=1000):
    """~-30 dB signal — between the LOW (-40) and HIGH (-25) silence
    thresholds. Hysteresis fixture: classified as silent when idle, as
    speech when already in a phrase."""
    return (np.ones(samples, dtype=np.int16) * amplitude).tobytes()


# is_silent -----------------------------------------------------------------

def test_is_silent_recognises_zeros():
    assert is_silent(silent_chunk())


def test_is_silent_rejects_loud_signal():
    assert not is_silent(loud_chunk())


# pseudo_streaming = False --------------------------------------------------

def test_pseudo_off_just_accumulates():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=False)
    backend.session = make_session()
    chunk = loud_chunk()
    result = backend.transcribe_realtime_audio(chunk)
    assert backend.session.audio_buffer == chunk
    assert "partial" in result


# pseudo_streaming = True: non-silent input ---------------------------------

def test_pseudo_on_loud_chunk_extends_audio_buffer():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    backend.session = make_session()
    chunk = loud_chunk()
    backend.transcribe_realtime_audio(chunk)
    # silence_buffer was empty -> pre-roll is empty -> audio_buffer == chunk
    assert backend.session.audio_buffer == chunk


# pseudo_streaming = True: silence shorter than silence_duration -> no commit

def test_pseudo_on_short_silence_does_not_commit():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    backend.session = make_session(
        audio_buffer=loud_chunk(),               # >= 100ms of speech in buffer
        last_sound_time=time.time() - 0.1,        # silent for 0.1s only
    )
    # Should NOT raise — under silence_duration threshold.
    backend.transcribe_realtime_audio(silent_chunk())


# pseudo_streaming = True: silence >= silence_duration -> commit ------------

# Audio buffer must clear AbstractTranscriber._CHUNK_MIN_MS (1500ms) for any
# cut to fire. Each loud_chunk(SR*2) = 2s of audio at 16 kHz.
_ABOVE_MIN = SR * 2


def test_pseudo_on_long_silence_does_not_commit_if_buffer_below_min():
    """_CHUNK_MIN_MS gates the cut even on long silence — protects Whisper
    from hallucinating on tiny chunks (e.g. "(music)", "Not to know.")."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    # 200ms of audio — well above old 100ms threshold, well below new 1500ms.
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=int(SR * 0.2)),
        last_sound_time=time.time() - 2.0,        # silent for 2s, plenty
    )
    # Should NOT raise — buffer under _CHUNK_MIN_MS.
    backend.transcribe_realtime_audio(silent_chunk())


def test_pseudo_on_long_silence_commits():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        last_sound_time=time.time() - 1.0,        # been silent 1s > 0.6s
    )
    with pytest.raises(SilenceDetected, match="Cut at silence"):
        backend.transcribe_realtime_audio(silent_chunk())


# Key recent change: commit even when elapsed < streaming_window ------------

def test_pseudo_on_commits_before_streaming_window_elapses():
    """Was: silence-cut required elapsed >= streaming_window. Now any silence
    pause >= silence_duration commits."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    now = time.time()
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        start_time=now - 2.0,                     # elapsed = 2s, well under 5s window
        last_sound_time=now - 1.0,                # silent for 1s > 0.6s
    )
    with pytest.raises(SilenceDetected):
        backend.transcribe_realtime_audio(silent_chunk())


# Force-cut at 2x streaming_window when there is no silence pause -----------

def test_pseudo_on_force_cut_at_double_window():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    now = time.time()
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        start_time=now - 11.0,                    # elapsed = 11s > 2*5s
        last_sound_time=now,                       # still actively speaking
    )
    with pytest.raises(SilenceDetected, match="Force-cut"):
        backend.transcribe_realtime_audio(loud_chunk())


# Hysteresis: silence_thresh_onset (HIGH) vs silence_thresh (LOW) -----------

def test_hysteresis_medium_chunk_treated_as_silent_when_idle():
    """audio_buffer empty -> use onset threshold (HIGH -25). A medium
    ~-30 dB frame is below -25 -> classified as silent, stays in
    silence_buffer."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_thresh=-40, silence_thresh_onset=-25,
                          silence_duration=0.6, streaming_window=5.0)
    backend.session = make_session()  # audio_buffer empty
    chunk = medium_chunk()
    backend.transcribe_realtime_audio(chunk)
    # Routed to silence_buffer because the onset threshold rejects it.
    assert backend.session.audio_buffer == b''
    assert backend.session.silence_buffer == chunk


def test_hysteresis_medium_chunk_treated_as_speech_when_in_phrase():
    """audio_buffer already has speech -> use pause threshold (LOW -40).
    Same -30 dB frame is above -40 -> classified as loud, extends the
    audio buffer."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_thresh=-40, silence_thresh_onset=-25,
                          silence_duration=0.6, streaming_window=5.0)
    backend.session = make_session(audio_buffer=loud_chunk())
    initial_len = len(backend.session.audio_buffer)
    backend.transcribe_realtime_audio(medium_chunk())
    # Speech path: appended (with 0s preroll since silence_buffer empty).
    assert len(backend.session.audio_buffer) > initial_len
    assert backend.session.silence_buffer == b''


# Pre-roll prepends last 0.5s of silence_buffer when speech resumes ---------

def test_speech_resumption_uses_last_half_second_preroll():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    # silence_buffer holds 1s of silence; pre-roll should grab last 0.5s
    backend.session = make_session(silence_buffer=silent_chunk(samples=SR))

    new_speech = loud_chunk(samples=1600)
    backend.transcribe_realtime_audio(new_speech)

    expected_preroll_bytes = int(0.5 * SR) * 2     # 0.5s of int16 mono
    assert len(backend.session.audio_buffer) == expected_preroll_bytes + len(new_speech)
    assert backend.session.silence_buffer == b''


# silence_buffer cap kicks in -----------------------------------------------

def test_silence_buffer_capped_at_5_seconds_default():
    """Default silence_duration=0.6 < 5s floor, so cap = 5s = 160 KB."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=0.6, streaming_window=5.0)
    backend.session = make_session(last_sound_time=time.time())  # sil_dur stays small -> no commit

    chunk = silent_chunk(samples=SR)               # 1s of silence per call
    for _ in range(30):                            # feed 30s of silence
        backend.transcribe_realtime_audio(chunk)

    expected_max = int(5.0 * SR) * 2
    assert len(backend.session.silence_buffer) <= expected_max


def test_silence_buffer_cap_follows_silence_duration_when_larger():
    """If user sets silence_duration=8s, cap follows to 8s (> 5s floor)."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          silence_duration=8.0, streaming_window=5.0)
    backend.session = make_session(last_sound_time=time.time())

    chunk = silent_chunk(samples=SR)
    for _ in range(30):
        backend.transcribe_realtime_audio(chunk)

    # cap == max(5, 8) == 8s
    expected_max = int(8.0 * SR) * 2
    assert len(backend.session.silence_buffer) <= expected_max
    # And clearly above the 5s floor (we fed 30s)
    assert len(backend.session.silence_buffer) > int(5.0 * SR) * 2


# is_streaming gate in app.py: pseudo_streaming flips it for batch backends -

def test_is_streaming_gate_includes_pseudo_streaming():
    """The output path (live paste vs paste-at-end) must treat a
    pseudo-streaming batch backend as streaming."""
    os.environ.setdefault('GROQ_API_KEY', 'dummy')
    from scribe.app import get_transcriber

    t_on = get_transcriber(
        backend='groq', model='whisper-large-v3-turbo',
        interactive=False, samplerate=SR, duration=120,
        silence_db=-40.0, silence_duration=0.6,
        pseudo_streaming=True, streaming_window=5.0,
    )
    is_streaming_on = (
        bool(getattr(t_on, "supports_streaming", False))
        or bool(getattr(t_on, "pseudo_streaming", False))
    )
    assert is_streaming_on is True

    t_off = get_transcriber(
        backend='groq', model='whisper-large-v3-turbo',
        interactive=False, samplerate=SR, duration=120,
        silence_db=-40.0, silence_duration=0.6,
        pseudo_streaming=False, streaming_window=5.0,
    )
    is_streaming_off = (
        bool(getattr(t_off, "supports_streaming", False))
        or bool(getattr(t_off, "pseudo_streaming", False))
    )
    assert is_streaming_off is False
