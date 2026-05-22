"""Unit tests for the Output dispatch in scribe.output.

Covers the surface that scribe.app.start_recording leans on:

- FileOutput appends chunks verbatim — no trailing ``\\n`` per chunk.
- KeyboardOutput re-applies the ``_coalesce_deltas`` hint on rebuild,
  so live-switching the typer / type_direct mid-recording correctly
  updates the streaming backend's coalescing behaviour.
- The live-switch signature ``(mode, typer, type_direct, output_file)``
  triggers an Output rebuild via the factory; passing a signature for
  an invalid combination (mode=file with no path) raises ValueError so
  the recording loop can fall back to the previous Output.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scribe.output import (
    ClipboardOutput,
    FileOutput,
    KeyboardOutput,
    TerminalOutput,
    make_output,
)


# ── FileOutput ────────────────────────────────────────────────────────


def test_file_output_appends_without_trailing_newline(tmp_path):
    """Each chunk is written verbatim. The realtime backend's per-word
    deltas no longer produce one-word-per-line; phrase chunks from the
    pseudo-streaming backends are concatenated without separators too —
    the file matches what the clipboard / keyboard sinks would deliver.
    """
    target = tmp_path / "out.txt"
    out = FileOutput(str(target))

    out.on_chunk("Hello", "Hello")
    out.on_chunk(" world", "Hello world")
    out.on_chunk(".", "Hello world.")
    out.on_finalize("Hello world.")

    assert target.read_text() == "Hello world."


def test_file_output_validates_path_at_construction(tmp_path):
    """Bad path must raise on ``__init__`` so the recording-loop's
    live-switch handler can fall back to the previous Output before any
    chunk hits the broken sink."""
    bad = tmp_path / "no_such_dir" / "out.txt"
    with pytest.raises((OSError, FileNotFoundError)):
        FileOutput(str(bad))


# ── KeyboardOutput coalesce hint ──────────────────────────────────────


class _FakeStreamingBackend:
    """Stub backend exposing the ``_coalesce_deltas`` slot the realtime
    backend uses. KeyboardOutput should set it according to (is_streaming,
    type_direct) on every construction."""

    def __init__(self):
        self._coalesce_deltas = None  # sentinel for "untouched"


def test_keyboard_output_sets_coalesce_hint_for_live_paste():
    """Streaming + paste => coalesce deltas (whole-word commit)."""
    backend = _FakeStreamingBackend()
    KeyboardOutput(typer_obj=None, type_direct=False, is_streaming=True,
                   backend_obj=backend, typer_name="auto")
    assert backend._coalesce_deltas is True


def test_keyboard_output_clears_coalesce_hint_for_type_direct():
    """Streaming + type-direct => stream raw per-delta (snappier UX)."""
    backend = _FakeStreamingBackend()
    # type_direct path needs a typer; smoke-test the hint patch only.
    KeyboardOutput(typer_obj=SimpleNamespace(name="fake", type=lambda *_: None),
                   type_direct=True, is_streaming=True,
                   backend_obj=backend, typer_name="auto")
    assert backend._coalesce_deltas is False


def test_keyboard_output_rebuild_reapplies_hint():
    """Rebuilding the KeyboardOutput after a live-switch must re-apply
    the hint — the recording loop relies on this for type-direct toggling
    mid-recording."""
    backend = _FakeStreamingBackend()
    # First sink: paste mode → coalesce on.
    KeyboardOutput(typer_obj=None, type_direct=False, is_streaming=True,
                   backend_obj=backend, typer_name="auto")
    assert backend._coalesce_deltas is True

    # User flips type_direct mid-recording → rebuild the Output.
    KeyboardOutput(typer_obj=SimpleNamespace(name="fake", type=lambda *_: None),
                   type_direct=True, is_streaming=True,
                   backend_obj=backend, typer_name="auto")
    assert backend._coalesce_deltas is False


# ── Factory / live-switch ─────────────────────────────────────────────


def test_make_output_dispatches_by_mode(tmp_path):
    """One assertion per mode: the factory picks the right concrete class
    so the recording loop's rebuild path lands on the right sink."""
    assert isinstance(
        make_output(mode="terminal", typer=None, type_direct=False,
                    output_file=None, is_streaming=False),
        TerminalOutput,
    )
    assert isinstance(
        make_output(mode="clipboard", typer=None, type_direct=False,
                    output_file=None, is_streaming=False),
        ClipboardOutput,
    )
    target = tmp_path / "x.txt"
    out_file = make_output(mode="file", typer=None, type_direct=False,
                           output_file=str(target), is_streaming=False)
    assert isinstance(out_file, FileOutput)
    assert out_file.path == str(target)


def test_make_output_file_mode_requires_path():
    """The recording loop's live-switch handler catches this ValueError
    and falls back to the previous Output — guard the factory side."""
    with pytest.raises(ValueError, match="output-file"):
        make_output(mode="file", typer=None, type_direct=False,
                    output_file=None, is_streaming=False)


def test_make_output_keystroke_paste_does_not_need_typer():
    """Paste-based keystroke delivery uses paste_via_clipboard which
    does its own pick_typer — the factory must not require an instance
    for paste mode (only for type-direct)."""
    out = make_output(mode="keystroke", typer="auto", type_direct=False,
                      output_file=None, is_streaming=True,
                      backend_obj=_FakeStreamingBackend())
    assert isinstance(out, KeyboardOutput)
    assert out.typer_obj is None


def test_live_switch_signature_triggers_rebuild(tmp_path):
    """End-to-end of the live-switch contract: build, swap o.mode, the
    signature compares unequal so the recording loop will rebuild."""
    from scribe.app import _output_signature

    target = tmp_path / "out.txt"
    o = SimpleNamespace(mode="clipboard", typer="auto",
                        type_direct=False, output_file=str(target))
    sig_before = _output_signature(o)

    # User toggles Output → File via tray.
    o.mode = "file"
    sig_after = _output_signature(o)

    assert sig_before != sig_after
    # The new signature builds the new sink without error.
    out = make_output(mode=o.mode, typer=o.typer, type_direct=o.type_direct,
                      output_file=o.output_file, is_streaming=False)
    assert isinstance(out, FileOutput)
