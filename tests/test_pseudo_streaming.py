"""Unit tests for pseudo-streaming pieces in scribe.models and the
is_streaming gate in scribe.app.

Covers the recent behaviour changes:
- silence-cut fires on any detected silence (no window floor)
- silence_buffer capped at max(5s, stream_chunk_silence_break)
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
    without needing a real STT model.

    Pins vad_mode="db" so the tests exercise the dB threshold gate
    deterministically — most fixtures use square waves that silero (the
    auto-mode pick when available) correctly classifies as non-speech."""
    name = "fake"
    backend = "fake"

    def __init__(self, *args, vad_mode="db", **kwargs):
        super().__init__(*args, vad_mode=vad_mode, **kwargs)

    def transcribe_audio(self, audio_bytes):
        return {"text": "fake"}

    def finalize(self):
        return {"text": "fake"}


def make_session(*, audio_buffer=b'', silence_buffer=b'',
                 start_time=None, last_sound_time=None, log_sink=None,
                 silence_intervals=None, silence_start_ms=None):
    now = time.time()
    sess = SimpleNamespace(
        audio_buffer=audio_buffer,
        silence_buffer=silence_buffer,
        # Auto-mode tracking lives on the session; default to empty/None
        # so tests that don't care don't have to touch them.
        silence_intervals=silence_intervals if silence_intervals is not None else [],
        silence_start_ms=silence_start_ms,
        start_time=start_time if start_time is not None else now,
        last_sound_time=last_sound_time if last_sound_time is not None else now,
        waiting=False,
    )
    # RecordingSession exposes this; the non-pseudo branch calls it.
    sess.get_elapsed = lambda: time.time() - sess.start_time
    # Context-reset branch logs via AbstractTranscriber.log → session.log;
    # accept an optional list sink so tests can assert on emitted messages.
    if log_sink is None:
        log_sink = []
    sess.log_sink = log_sink
    sess.log = lambda msg: log_sink.append(msg)
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
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0)
    backend.session = make_session()
    chunk = loud_chunk()
    backend.transcribe_realtime_audio(chunk)
    # silence_buffer was empty -> pre-roll is empty -> audio_buffer == chunk
    assert backend.session.audio_buffer == chunk


# pseudo_streaming = True: silence shorter than stream_chunk_silence_break -> no commit

def test_pseudo_on_short_silence_does_not_commit():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0)
    backend.session = make_session(
        audio_buffer=loud_chunk(),               # >= 100ms of speech in buffer
        last_sound_time=time.time() - 0.1,        # silent for 0.1s only
    )
    # Should NOT raise — under stream_chunk_silence_break threshold.
    backend.transcribe_realtime_audio(silent_chunk())


# pseudo_streaming = True: silence >= stream_chunk_silence_break -> commit ----

# Audio buffer must clear stream_chunk_min (1.5s default) for any cut to
# fire. Each loud_chunk(SR*2) = 2s of audio at 16 kHz.
_ABOVE_MIN = SR * 2


def test_pseudo_on_long_silence_does_not_commit_if_buffer_below_min():
    """stream_chunk_min gates the cut even on long silence — protects Whisper
    from hallucinating on tiny chunks (e.g. "(music)", "Not to know.")."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0)
    # 200ms of audio — well above old 100ms threshold, well below new 1500ms.
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=int(SR * 0.2)),
        last_sound_time=time.time() - 2.0,        # silent for 2s, plenty
    )
    # Should NOT raise — buffer under _CHUNK_MIN_MS.
    backend.transcribe_realtime_audio(silent_chunk())


def test_pseudo_on_long_silence_commits():
    # stream_first_chunk_min=1.5 opts out of the bootstrap-chunk floor so
    # this test exercises silence-cut mechanics at the regular chunk_min,
    # not the first-chunk override (covered separately below).
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0,
                          stream_first_chunk_min=1.5)
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        last_sound_time=time.time() - 1.0,        # been silent 1s > 0.6s
    )
    with pytest.raises(SilenceDetected, match="Cut at silence"):
        backend.transcribe_realtime_audio(silent_chunk())


# First-chunk-min: bootstrap floor when the rolling context is empty --------

def test_first_chunk_min_blocks_silence_cut_below_floor():
    """With empty context + context_length > 0, the silence-cut should
    require buffer >= stream_first_chunk_min (not the regular chunk_min).
    A 2 s buffer between the two floors should NOT trigger a cut."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0,
                          stream_chunk_min=1.5, stream_first_chunk_min=3.0,
                          stream_context_length=200)
    backend._streaming_context = ""  # explicit: first chunk
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),   # 2s, between the floors
        last_sound_time=time.time() - 1.0,             # silent 1s > 0.6s break
    )
    # Would have cut at the regular 1.5s floor — first-chunk override holds it.
    backend.transcribe_realtime_audio(silent_chunk())


def test_first_chunk_min_allows_cut_when_buffer_above_floor():
    """Same setup but the buffer clears the first-chunk floor — cut fires."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0,
                          stream_chunk_min=1.5, stream_first_chunk_min=3.0,
                          stream_context_length=200)
    backend._streaming_context = ""
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=SR * 4),       # 4s > first_chunk_min
        last_sound_time=time.time() - 1.0,
    )
    with pytest.raises(SilenceDetected, match="Cut at silence"):
        backend.transcribe_realtime_audio(silent_chunk())


def test_first_chunk_min_inactive_once_context_populated():
    """After the first chunk's text seeds the rolling tail, subsequent
    chunks fall back to the regular stream_chunk_min — a 2s buffer cuts
    even though it's below first_chunk_min."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0,
                          stream_chunk_min=1.5, stream_first_chunk_min=3.0,
                          stream_context_length=200)
    backend._streaming_context = "Some prior chunk's tail."
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),   # 2s, above regular floor
        last_sound_time=time.time() - 1.0,
    )
    with pytest.raises(SilenceDetected, match="Cut at silence"):
        backend.transcribe_realtime_audio(silent_chunk())


def test_first_chunk_min_inactive_in_patient_mode():
    """Patient profile uses stream_context_length=0 → context never
    populates. The first-chunk override is gated on context_length > 0
    so Patient-mode users keep their configured chunk_min for every
    chunk and short utterances stay committable."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=300.0,
                          stream_chunk_min=0.5, stream_first_chunk_min=3.0,
                          stream_context_length=0)  # Patient
    backend._streaming_context = ""  # always empty in this mode
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=int(SR * 0.8)),  # 0.8s > 0.5s, < 3.0s
        last_sound_time=time.time() - 1.0,
    )
    with pytest.raises(SilenceDetected, match="Cut at silence"):
        backend.transcribe_realtime_audio(silent_chunk())


def test_first_chunk_min_clamped_to_chunk_max():
    """If first_chunk_min > stream_chunk_max the chunker would never be
    able to commit a first chunk. Clamp at use time so misconfiguration
    can't deadlock — first_chunk_min effectively becomes chunk_max."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=5.0,
                          stream_chunk_min=1.5, stream_first_chunk_min=20.0,
                          stream_context_length=200)
    backend._streaming_context = ""
    now = time.time()
    backend.session = make_session(
        # 5.5s buffer + elapsed past chunk_max → force-cut path.
        # Without clamp: buffer would have to clear 20s. With clamp: 5s suffices.
        audio_buffer=loud_chunk(samples=int(SR * 5.5)),
        start_time=now - 6.0,
        last_sound_time=now,
    )
    with pytest.raises(SilenceDetected, match="Force-cut"):
        backend.transcribe_realtime_audio(loud_chunk())


# Silence-cut fires before chunk-max elapses ----------------------------------

def test_pseudo_on_commits_before_chunk_max_elapses():
    """Silence-cut fires whenever a pause >= stream_chunk_silence_break is detected,
    regardless of how much elapsed time has accumulated."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0,
                          stream_first_chunk_min=1.5)
    now = time.time()
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        start_time=now - 2.0,                     # elapsed = 2s, well under 5s window
        last_sound_time=now - 1.0,                # silent for 1s > 0.6s
    )
    with pytest.raises(SilenceDetected):
        backend.transcribe_realtime_audio(silent_chunk())


# Force-cut at stream_chunk_max when there is no silence pause ---------------

def test_pseudo_on_force_cut_at_chunk_max():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0,
                          stream_first_chunk_min=1.5)
    now = time.time()
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        start_time=now - 11.0,                    # elapsed = 11s > chunk_max=10s
        last_sound_time=now,                       # still actively speaking
    )
    with pytest.raises(SilenceDetected, match="Force-cut"):
        backend.transcribe_realtime_audio(loud_chunk())


# Pre-roll prepends last 0.5s of silence_buffer when speech resumes ---------

def test_speech_resumption_uses_last_half_second_preroll():
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0)
    # silence_buffer holds 1s of silence; pre-roll should grab last 0.5s
    backend.session = make_session(silence_buffer=silent_chunk(samples=SR))

    new_speech = loud_chunk(samples=1600)
    backend.transcribe_realtime_audio(new_speech)

    expected_preroll_bytes = int(0.5 * SR) * 2     # 0.5s of int16 mono
    assert len(backend.session.audio_buffer) == expected_preroll_bytes + len(new_speech)
    assert backend.session.silence_buffer == b''


# silence_buffer cap kicks in -----------------------------------------------

def test_silence_buffer_capped_at_5_seconds_default():
    """Default stream_chunk_silence_break=0.6 < 5s floor, so cap = 5s = 160 KB."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0.6, stream_chunk_max=10.0)
    backend.session = make_session(last_sound_time=time.time())  # sil_dur stays small -> no commit

    chunk = silent_chunk(samples=SR)               # 1s of silence per call
    for _ in range(30):                            # feed 30s of silence
        backend.transcribe_realtime_audio(chunk)

    expected_max = int(5.0 * SR) * 2
    assert len(backend.session.silence_buffer) <= expected_max


def test_silence_buffer_cap_follows_silence_break_when_larger():
    """If user sets stream_chunk_silence_break=8s, cap follows to 8s (> 5s floor)."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=8.0, stream_chunk_max=10.0)
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
        interactive=False, samplerate=SR, clip_timeout=120,
        silence_db=-40.0, stream_chunk_silence_break=0.6,
        pseudo_streaming=True, stream_chunk_max=10.0,
    )
    is_streaming_on = (
        bool(getattr(t_on, "supports_streaming", False))
        or bool(getattr(t_on, "pseudo_streaming", False))
    )
    assert is_streaming_on is True

    t_off = get_transcriber(
        backend='groq', model='whisper-large-v3-turbo',
        interactive=False, samplerate=SR, clip_timeout=120,
        silence_db=-40.0, stream_chunk_silence_break=0.6,
        pseudo_streaming=False, stream_chunk_max=10.0,
    )
    is_streaming_off = (
        bool(getattr(t_off, "supports_streaming", False))
        or bool(getattr(t_off, "pseudo_streaming", False))
    )
    assert is_streaming_off is False


# Rolling chunk-tail prompt context: reset on long inter-utterance pauses ----

def _make_pseudo_backend(**overrides):
    kwargs = dict(model=None, samplerate=SR, pseudo_streaming=True,
                  stream_chunk_silence_break=0.6, stream_chunk_max=10.0)
    kwargs.update(overrides)
    return FakeBackend(**kwargs)


def test_context_reset_short_pause_preserves_context():
    """A pause shorter than the resolved context-reset threshold keeps the
    rolling prompt — short intra-sentence punctuation breaks should still
    benefit from cross-chunk grammar continuity."""
    backend = _make_pseudo_backend()
    backend.session = make_session(last_sound_time=time.time() - 0.5)
    backend._streaming_context = "previous sentence."

    backend.transcribe_realtime_audio(loud_chunk())

    assert backend._streaming_context == "previous sentence."


def test_context_reset_long_pause_clears_context():
    """A pause >= the resolved context-reset threshold between two utterances drops the
    rolling prompt — protects the new utterance from being biased toward
    the old one."""
    backend = _make_pseudo_backend()
    backend.session = make_session(last_sound_time=time.time() - 2.0)
    backend._streaming_context = "write a test"

    backend.transcribe_realtime_audio(loud_chunk())

    assert backend._streaming_context == ""
    assert any("Clearing chunk context" in m
               for m in backend.session.log_sink)


def test_context_reset_at_exact_threshold_clears():
    """Boundary: sil_dur == resolved threshold (multiplier × silence-break) clears (>= check)."""
    backend = _make_pseudo_backend()
    threshold = backend.stream_context_reset_silence * backend.stream_chunk_silence_break
    # Subtract a tiny epsilon FROM the past so by the time
    # transcribe_realtime_audio computes time.time() - last_sound_time the
    # gap is just above threshold. Avoids flakiness from clock granularity.
    backend.session = make_session(last_sound_time=time.time() - (threshold + 0.05))
    backend._streaming_context = "stale"

    backend.transcribe_realtime_audio(loud_chunk())

    assert backend._streaming_context == ""


def test_context_reset_mid_chunk_with_long_pause_also_clears():
    """Mid-utterance long pauses (audio_buffer non-empty AND sil_dur >= reset threshold)
    also clear context. We dropped the `not session.audio_buffer` guard
    because a single noise spike during an inter-utterance pause was
    enough to fill audio_buffer below the commit floor and block the
    reset (see test_context_reset_survives_noise_spike_during_pause).
    Sacrificing the rare genuine mid-utterance case is the accepted
    trade-off: a ≥1.8s break inside one sentence is unusual, and even
    then losing one sentence of cross-chunk priming is mild compared to
    the self-reinforcing contamination loop the guard was enabling."""
    backend = _make_pseudo_backend()
    backend.session = make_session(
        audio_buffer=loud_chunk(),
        last_sound_time=time.time() - 3.0,
    )
    backend._streaming_context = "drop me"

    backend.transcribe_realtime_audio(loud_chunk())

    assert backend._streaming_context == ""


def test_context_reset_empty_context_no_log_no_change():
    """No streaming_context to clear → branch must be a no-op (no log spam,
    no state change). Protects against the empty-string case being treated
    as needing a reset every time speech resumes after a pause."""
    backend = _make_pseudo_backend()
    backend.session = make_session(last_sound_time=time.time() - 5.0)
    assert backend._streaming_context == ""

    backend.transcribe_realtime_audio(loud_chunk())

    assert backend._streaming_context == ""
    assert not any("Clearing chunk context" in m
                   for m in backend.session.log_sink)


def test_context_preserved_when_no_pause_yet():
    """Speech resumes immediately after an in-progress phrase (sil_dur ~ 0):
    context must be preserved so chunk-to-chunk grammar carries."""
    backend = _make_pseudo_backend()
    backend.session = make_session(last_sound_time=time.time())  # just spoke
    backend._streaming_context = "in-flight phrase"

    backend.transcribe_realtime_audio(loud_chunk())

    assert backend._streaming_context == "in-flight phrase"


# Regression: pause poisoned by a single noise spike still resets context ---

def test_context_reset_survives_noise_spike_during_pause():
    """Regression for the reported bug:

      1. User finishes a phrase → commit fires → context = "write a test".
      2. During the pause, a single brief noise spike crosses the silence
         threshold (keyboard click, fan, breath).
      3. The user pauses for several seconds (well over the context-reset threshold).
      4. The user resumes a new phrase.

    Before the fix the reset was gated on `not session.audio_buffer`; the
    spike at (2) filled the buffer (~550 ms of preroll+spike) below the
    1500 ms commit floor, so the buffer never emptied and the reset at
    (4) was skipped. Symptom: the stale prompt biased every subsequent
    chunk, causing self-reinforcing "write a test, write a test, ..."
    transcriptions.
    """
    backend = _make_pseudo_backend()
    backend.session = make_session(last_sound_time=time.time())
    backend._streaming_context = "write a test"

    # (2) brief noise spike during pause
    backend.transcribe_realtime_audio(loud_chunk(samples=int(SR * 0.05)))
    assert backend.session.audio_buffer, "spike should have landed in buffer"

    # (3) long silent pause (well over the context-reset threshold).
    # We don't have a way to advance time without sleeping; nudge
    # last_sound_time backwards instead.
    backend.session.last_sound_time = time.time() - 3.0
    # Feed silence chunks during the pause — they should not commit
    # (buffer < 1500ms after the 50ms spike + 500ms preroll = ~550ms).
    for _ in range(5):
        backend.transcribe_realtime_audio(silent_chunk())

    # (4) real speech resumes after the long pause. THIS is the moment
    # the context reset should fire — but it won't, because audio_buffer
    # is non-empty from the spike.
    backend.transcribe_realtime_audio(loud_chunk())

    assert backend._streaming_context == ""


# Auto mode (stream_chunk_silence_break == 0) and Max mode (== None) ---------

def test_auto_mode_cuts_at_longest_valid_silence():
    """Auto mode: at force-cut, pick the longest silence whose start is
    past stream_chunk_min; trim audio_buffer there and stash the trailing
    in _pending_chunk_audio for the next chunk."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0,
                          stream_chunk_min=1.5, stream_first_chunk_min=1.5,
                          stream_chunk_max=10.0)
    now = time.time()
    # 12s of audio in buffer — comfortably bigger than the cut offset
    # below, so the slice is well-defined.
    audio = loud_chunk(samples=SR * 12)
    backend.session = make_session(
        audio_buffer=audio,
        start_time=now - 11.0,           # elapsed > chunk_max
        last_sound_time=now,
        # Two candidate silences, both past chunk_min (1500ms):
        # the second one is longer (1500ms vs 500ms) and should win.
        silence_intervals=[(2000.0, 500.0), (5000.0, 1500.0)],
    )

    with pytest.raises(SilenceDetected, match="Auto-cut"):
        backend.transcribe_realtime_audio(loud_chunk())

    expected_cut_bytes = int(5000 / 1000.0 * SR) * 2
    assert len(backend.session.audio_buffer) == expected_cut_bytes
    # Pending audio = everything after the cut (preroll silence + the
    # post-silence speech that was already in the buffer + the speech
    # we just fed in this call).
    assert backend._pending_chunk_audio
    assert (len(backend.session.audio_buffer) + len(backend._pending_chunk_audio)
            == len(audio) + len(loud_chunk()))


def test_auto_mode_falls_back_to_force_cut_when_no_valid_silence():
    """Auto mode: if no tracked silence starts past stream_chunk_min,
    fall back to the brute force-cut at chunk_max."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=0,
                          stream_chunk_min=1.5, stream_first_chunk_min=1.5,
                          stream_chunk_max=10.0)
    now = time.time()
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        start_time=now - 11.0,
        last_sound_time=now,
        # Only silence is at 500ms, well below chunk_min (1500ms).
        silence_intervals=[(500.0, 2000.0)],
    )

    with pytest.raises(SilenceDetected, match="Force-cut"):
        backend.transcribe_realtime_audio(loud_chunk())

    # No re-cut happened; pending stays empty.
    assert backend._pending_chunk_audio == b''


def test_max_mode_disables_silence_cut():
    """Max mode (stream_chunk_silence_break is None): even a long silence
    must not commit. Only the force-cut at chunk_max can ever fire."""
    backend = FakeBackend(model=None, samplerate=SR, pseudo_streaming=True,
                          stream_chunk_silence_break=None,
                          stream_chunk_max=10.0)
    backend.session = make_session(
        audio_buffer=loud_chunk(samples=_ABOVE_MIN),
        last_sound_time=time.time() - 5.0,   # 5s of silence, well past anything
    )

    # Must not raise — Max mode has no silence-cut path.
    backend.transcribe_realtime_audio(silent_chunk())
