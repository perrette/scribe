"""Tests for the Prompt / Words file pickers in the Options menu.

Verifies:
- cb_pick_prompt_file_path / cb_pick_words_file_path route through
  scribe.dialog.select_file_open (mocked — no tk required).
- On OK: writes the chosen path into o.prompt_file / o.words_file AND
  mirrors into self.params; live transcriber's _prompt / _hotwords are
  refreshed via the resolve-and-compose pipeline.
- On Cancel (None): leaves o + transcriber state untouched.
- Pre-populates initial_dir / initial_file from the current value.
"""
from types import SimpleNamespace

import pytest

from scribe import dialog as scribe_dialog
from scribe.menu import AppState


def _make_state(*, prompt_file=None, words_file=None, transcriber=None):
    o = SimpleNamespace(
        prompt=None, prompt_file=prompt_file,
        words=None, words_file=words_file,
    )
    return AppState(o=o, transcriber=transcriber)


def _fake_transcriber(backend, **attrs):
    """Minimal stand-in: holds .backend + the _prompt/_hotwords slots the
    refresh helper mutates. Whisper grows a _hotwords attr; the others
    don't, matching the real backends."""
    t = SimpleNamespace(backend=backend, _prompt=None)
    if backend == "whisper":
        t._hotwords = None
    for k, v in attrs.items():
        setattr(t, k, v)
    return t


def test_pick_prompt_file_ok(monkeypatch, tmp_path):
    captured = {}
    promptfile = tmp_path / "prompt.txt"
    promptfile.write_text("Patient notes from a cardiology consult.")

    def fake_picker(title="Choose file", initial_dir=None,
                    initial_file=None, filetypes=None):
        captured["title"] = title
        captured["initial_dir"] = initial_dir
        captured["initial_file"] = initial_file
        return str(promptfile)

    monkeypatch.setattr(scribe_dialog, "select_file_open", fake_picker)

    t = _fake_transcriber("groq")
    state = _make_state(transcriber=t)
    result = state.cb_pick_prompt_file_path(view=None, item=None)

    assert result is True
    assert state.o.prompt_file == str(promptfile)
    assert state.params["prompt_file"] == str(promptfile)
    assert "Patient notes" in t._prompt
    assert "Choose prompt file" in captured["title"]


def test_pick_words_file_ok_formats_as_punctuated_for_groq(monkeypatch, tmp_path):
    """End-to-end: picking a words file on a Groq transcriber renders the
    words as "Tierney, Comet." in _prompt — the auto-format rule."""
    wordsfile = tmp_path / "words.txt"
    wordsfile.write_text("Tierney Comet")

    monkeypatch.setattr(scribe_dialog, "select_file_open",
                        lambda **_: str(wordsfile))

    t = _fake_transcriber("groq")
    state = _make_state(transcriber=t)
    result = state.cb_pick_words_file_path(view=None, item=None)

    assert result is True
    assert state.o.words_file == str(wordsfile)
    assert t._prompt == "Tierney, Comet."


def test_pick_words_file_ok_routes_hotwords_for_whisper(monkeypatch, tmp_path):
    """On the faster-whisper backend, words go to the dedicated hotwords
    channel — _prompt stays empty (or carries only the prompt text)."""
    wordsfile = tmp_path / "words.txt"
    wordsfile.write_text("Tierney Comet")

    monkeypatch.setattr(scribe_dialog, "select_file_open",
                        lambda **_: str(wordsfile))

    t = _fake_transcriber("whisper")
    state = _make_state(transcriber=t)
    state.cb_pick_words_file_path(view=None, item=None)

    assert t._prompt is None  # no prompt text given, words shouldn't leak in
    assert t._hotwords == "Tierney Comet"


def test_pick_prompt_file_cancel_is_noop(monkeypatch):
    monkeypatch.setattr(scribe_dialog, "select_file_open", lambda **_: None)

    t = _fake_transcriber("groq", _prompt="prev")
    state = _make_state(prompt_file="/old/path.txt", transcriber=t)
    result = state.cb_pick_prompt_file_path(view=None, item=None)

    assert result is True
    assert state.o.prompt_file == "/old/path.txt"
    assert "prompt_file" not in state.params or state.params["prompt_file"] == "/old/path.txt"
    assert t._prompt == "prev"


def test_pick_prompt_file_prepopulates_from_current(monkeypatch, tmp_path):
    captured = {}

    def fake_picker(title="Choose file", initial_dir=None,
                    initial_file=None, filetypes=None):
        captured["initial_dir"] = initial_dir
        captured["initial_file"] = initial_file
        return None  # cancel — we only care about pre-population

    monkeypatch.setattr(scribe_dialog, "select_file_open", fake_picker)

    state = _make_state(prompt_file="/home/u/cfg/notes.txt")
    state.cb_pick_prompt_file_path(view=None, item=None)

    assert captured["initial_dir"] == "/home/u/cfg"
    assert captured["initial_file"] == "notes.txt"


def test_reload_picks_up_disk_edit(monkeypatch, tmp_path):
    """User edits words.txt in a text editor; clicking Reload re-reads
    the file without re-opening the picker dialog."""
    wordsfile = tmp_path / "words.txt"
    wordsfile.write_text("Tierney")

    t = _fake_transcriber("groq")
    state = _make_state(words_file=str(wordsfile), transcriber=t)

    # First reload: picks up the initial content.
    state.cb_reload_prompt_files(view=None, item=None)
    assert t._prompt == "Tierney."

    # Simulate the user editing the file externally.
    wordsfile.write_text("Tierney Comet")

    # Second reload: same file path, fresh content.
    state.cb_reload_prompt_files(view=None, item=None)
    assert t._prompt == "Tierney, Comet."


def test_pick_prompt_file_no_transcriber_is_safe(monkeypatch, tmp_path):
    """During early menu construction (no transcriber yet) the picker must
    not crash — it should still update o + params and skip the refresh."""
    promptfile = tmp_path / "prompt.txt"
    promptfile.write_text("hello")

    monkeypatch.setattr(scribe_dialog, "select_file_open",
                        lambda **_: str(promptfile))

    state = _make_state(transcriber=None)
    result = state.cb_pick_prompt_file_path(view=None, item=None)

    assert result is True
    assert state.o.prompt_file == str(promptfile)
