"""Unit test for the Choose path… action in the Output submenu.

Verifies that cb_pick_output_file_path:
- Routes through scribe.dialog.select_file_save (mocked here — no tk required).
- On OK: writes the chosen path into o.output_file AND switches o.mode to
  "file"; both are mirrored into self.params.
- On Cancel (None): leaves o.output_file and o.mode untouched.
- Pre-populates initial_dir / initial_file from the current o.output_file.
"""
from types import SimpleNamespace

import pytest

from scribe import dialog as scribe_dialog
from scribe.menu import AppState


def _make_state(output_file=None, mode="keystroke"):
    o = SimpleNamespace(output_file=output_file, mode=mode)
    return AppState(o=o)


def test_pick_output_file_path_ok_sets_path_and_mode(monkeypatch):
    captured = {}

    def fake_picker(title="Choose output file", initial_dir=None,
                    initial_file="scribe-transcript.txt"):
        captured["initial_dir"] = initial_dir
        captured["initial_file"] = initial_file
        return "/tmp/notes/out.txt"

    monkeypatch.setattr(scribe_dialog, "select_file_save", fake_picker)

    state = _make_state(output_file="/home/user/old.txt", mode="clipboard")
    result = state.cb_pick_output_file_path(view=None, item=None)

    assert result is True
    assert state.o.output_file == "/tmp/notes/out.txt"
    assert state.o.mode == "file"
    assert state.params["output_file"] == "/tmp/notes/out.txt"
    assert state.params["mode"] == "file"
    # Picker pre-population pulled from the prior path.
    assert captured["initial_dir"] == "/home/user"
    assert captured["initial_file"] == "old.txt"


def test_pick_output_file_path_cancel_is_noop(monkeypatch):
    monkeypatch.setattr(scribe_dialog, "select_file_save", lambda **_: None)

    state = _make_state(output_file=None, mode="clipboard")
    result = state.cb_pick_output_file_path(view=None, item=None)

    assert result is True
    assert state.o.output_file is None
    assert state.o.mode == "clipboard"
    assert state.params.get("output_file") is None
    assert state.params.get("mode") in (None, "clipboard")
