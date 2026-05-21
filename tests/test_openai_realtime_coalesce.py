"""Unit tests for the realtime delta-coalescing layer.

The gpt-realtime-whisper backend emits per-word/per-subword deltas at
~30-80 ms intervals. Pasting each one through paste_via_clipboard
caused token drops and duplications because Wayland's wl-copy can't
settle between consecutive deltas. feed_audio now batches deltas into
`_delta_buffer` and emits only when the flush interval elapsed or the
buffer ends on sentence-final punctuation.

These tests skip the network side: we leave `_connection = None` and
pass an empty audio chunk so feed_audio's send block is a no-op, then
push synthetic delta events directly onto `_event_queue`.
"""
import time

import pytest

from scribe.backends.openai_realtime import OpenaiRealtimeTranscriber


class FakeSession:
    def __init__(self):
        self.audio_buffer = b""

    def notify_error(self, title, message):
        # Recorded so tests can assert on error surfacing.
        self.errors = getattr(self, "errors", [])
        self.errors.append((title, message))

    def log(self, msg):
        pass


@pytest.fixture
def tr():
    backend = OpenaiRealtimeTranscriber(model_name="gpt-realtime-whisper",
                                        model=object())
    backend.session = FakeSession()
    # Anchor the flush clock so each test starts from a known baseline.
    backend._last_delta_flush = time.time()
    return backend


def push_delta(tr, text):
    tr._event_queue.put({"text": text})


def drain(tr):
    return list(tr.feed_audio(b""))


def test_single_delta_within_interval_is_buffered(tr):
    push_delta(tr, " hello")
    assert drain(tr) == []
    assert tr._delta_buffer == " hello"


def test_multiple_deltas_accumulate_until_interval(tr):
    push_delta(tr, " hello")
    push_delta(tr, " world")
    push_delta(tr, " how")
    assert drain(tr) == []
    assert tr._delta_buffer == " hello world how"


def test_punctuation_triggers_immediate_flush(tr):
    push_delta(tr, " hello")
    push_delta(tr, " world.")
    out = drain(tr)
    assert out == [{"text": " hello world."}]
    assert tr._delta_buffer == ""


@pytest.mark.parametrize("trailing", [".", "!", "?", "\n"])
def test_each_sentence_final_punctuation_flushes(tr, trailing):
    push_delta(tr, f" done{trailing}")
    out = drain(tr)
    assert out == [{"text": f" done{trailing}"}]


def test_comma_does_not_trigger_flush(tr):
    # Comma is mid-sentence; should stay buffered.
    push_delta(tr, " hello,")
    push_delta(tr, " world")
    assert drain(tr) == []
    assert tr._delta_buffer == " hello, world"


def test_interval_elapsed_triggers_flush(tr):
    push_delta(tr, " accumulated")
    # Simulate the interval having elapsed by backdating the last flush.
    tr._last_delta_flush = time.time() - (tr._DELTA_FLUSH_INTERVAL_S + 0.05)
    out = drain(tr)
    assert out == [{"text": " accumulated"}]
    assert tr._delta_buffer == ""


def test_empty_buffer_does_not_emit_even_after_interval(tr):
    # Stale clock + no deltas → nothing yielded.
    tr._last_delta_flush = time.time() - 10.0
    assert drain(tr) == []


def test_flush_resets_the_interval_clock(tr):
    # First flush via punctuation.
    push_delta(tr, " first.")
    drain(tr)
    after_first = tr._last_delta_flush
    # Second delta arrives right after — should NOT immediately flush
    # because the clock was just reset.
    push_delta(tr, " second")
    assert drain(tr) == []
    assert tr._last_delta_flush == after_first


def test_error_events_bypass_buffer_and_surface_immediately(tr):
    tr._event_queue.put({"_error": ("Realtime error", "boom")})
    push_delta(tr, " text")
    # Error reaches notify_error; the regular delta stays buffered.
    drain(tr)
    assert tr.session.errors == [("Realtime error", "boom")]
    assert tr._delta_buffer == " text"


def test_finalize_flushes_remaining_buffer(tr):
    # Bypass the early-return and commit paths in finalize.
    tr._connection = object()
    tr._closed = False
    tr._has_uncommitted_audio = False
    push_delta(tr, " hello")
    drain(tr)
    assert tr._delta_buffer == " hello"  # still pending
    result = tr.finalize()
    assert result == {"text": " hello"}
    assert tr._delta_buffer == ""


def test_finalize_combines_buffer_and_tail_deltas(tr):
    tr._connection = object()
    tr._closed = False
    tr._has_uncommitted_audio = False
    # Buffered (not yet flushed) + tail (arrived post-stop).
    tr._delta_buffer = " buffered"
    tr._event_queue.put({"text": " tail"})
    result = tr.finalize()
    assert result == {"text": " buffered tail"}


def test_finalize_returns_empty_when_closed(tr):
    tr._closed = True
    tr._delta_buffer = " should not leak"
    assert tr.finalize() == {"text": ""}
