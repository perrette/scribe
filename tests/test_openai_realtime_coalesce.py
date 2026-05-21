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
    # Backdate the flush clock past _DELTA_FLUSH_MIN_INTERVAL_S so the
    # floor doesn't block punctuation-triggered tests. The
    # explicit-floor tests reset the clock themselves.
    backend._last_delta_flush = (time.time()
                                 - backend._DELTA_FLUSH_MIN_INTERVAL_S
                                 - 0.05)
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


def test_floor_blocks_back_to_back_punctuation_flushes(tr):
    # Two sentences arrive in quick succession. The first flushes
    # immediately on its period. The second should be HELD until the
    # floor has elapsed, otherwise its paste would race the first
    # through the clipboard.
    push_delta(tr, " one.")
    out = drain(tr)
    assert out == [{"text": " one."}]
    # Right after the flush: even a punctuation-terminated buffer
    # cannot trigger a second flush yet.
    push_delta(tr, " two.")
    assert drain(tr) == []
    assert tr._delta_buffer == " two."


def test_floor_releases_punctuation_flush_after_min_interval(tr):
    push_delta(tr, " one.")
    drain(tr)
    # Backdate the flush clock past the floor; the buffered ".-ending"
    # text now becomes eligible.
    tr._last_delta_flush = time.time() - tr._DELTA_FLUSH_MIN_INTERVAL_S - 0.01
    push_delta(tr, " two.")
    out = drain(tr)
    assert out == [{"text": " two."}]


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


# Bypass mode (type-direct / ydotool): no clipboard race exists, the app
# wants per-delta yields so each token hits the typer immediately.

def test_bypass_mode_yields_each_delta_raw(tr):
    tr._coalesce_deltas = False
    push_delta(tr, " hello")
    push_delta(tr, " world")
    push_delta(tr, ".")
    out = drain(tr)
    assert out == [{"text": " hello"}, {"text": " world"}, {"text": "."}]
    # Nothing accumulated in the coalescing buffer.
    assert tr._delta_buffer == ""


def test_bypass_mode_does_not_set_flush_clock(tr):
    tr._coalesce_deltas = False
    before = tr._last_delta_flush
    push_delta(tr, " hello.")
    drain(tr)
    # No flush event happened — the clock anchor stays put.
    assert tr._last_delta_flush == before


def test_bypass_mode_still_surfaces_errors(tr):
    tr._coalesce_deltas = False
    tr._event_queue.put({"_error": ("Realtime error", "boom")})
    push_delta(tr, " text")
    out = drain(tr)
    assert out == [{"text": " text"}]
    assert tr.session.errors == [("Realtime error", "boom")]


def test_default_mode_is_coalesce_on(tr):
    # Sanity: the constructor defaults to coalescing-on so backends
    # used outside the scribe app loop (smoke tests, library use) get
    # the safer batched behaviour.
    assert tr._coalesce_deltas is True
