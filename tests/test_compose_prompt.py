"""Tests for the words-auto-format / prompt-composition helpers in app.py.

`--words` is semantically a wordlist but ends up joined into a Whisper
prompt for backends without a dedicated hotwords channel. Whisper mirrors
prompt style, so a bare wordlist prompt biases the model toward
unpunctuated output. `compose_prompt_for_backend` normalises this by
rendering words as a comma-list with a terminal period — except on
faster-whisper, where words travel via the dedicated hotwords channel.
"""
from types import SimpleNamespace

import pytest

from scribe.app import (_format_words_for_prompt, autodiscover_prompt_files,
                        compose_prompt_for_backend)


# ── _format_words_for_prompt ─────────────────────────────────────────────

def test_format_words_basic():
    assert _format_words_for_prompt(["Tierney", "Comet"]) == "Tierney, Comet."


def test_format_words_single():
    assert _format_words_for_prompt(["Tierney"]) == "Tierney."


def test_format_words_strips_user_punctuation():
    """If the user already wrote 'Tierney., Comet..' we shouldn't end up
    with 'Tierney., Comet...'. Strip stray trailing punctuation per word."""
    assert _format_words_for_prompt(["Tierney.", "Comet,"]) == "Tierney, Comet."


def test_format_words_empty():
    assert _format_words_for_prompt([]) == ""
    assert _format_words_for_prompt(None) == ""


def test_format_words_drops_blank_entries():
    assert _format_words_for_prompt(["Tierney", "", "  ", "Comet"]) == "Tierney, Comet."


# ── compose_prompt_for_backend ────────────────────────────────────────────

@pytest.mark.parametrize("backend", ["whisper-futo", "openai", "groq", "vosk"])
def test_compose_joins_words_as_punctuated_for_non_hotwords(backend):
    prompt, hotwords = compose_prompt_for_backend(backend, None, ["Tierney", "Comet"])
    assert prompt == "Tierney, Comet."
    assert hotwords is None


def test_compose_keeps_hotwords_separate_for_faster_whisper():
    prompt, hotwords = compose_prompt_for_backend("whisper", None, ["Tierney", "Comet"])
    assert prompt is None
    assert hotwords == "Tierney Comet"  # hotwords channel: raw space-joined


def test_compose_prompt_only():
    prompt, hotwords = compose_prompt_for_backend("groq", "Medical notes.", None)
    assert prompt == "Medical notes."
    assert hotwords is None


def test_compose_prompt_plus_words_for_groq():
    prompt, hotwords = compose_prompt_for_backend("groq", "Medical notes.", ["AFib"])
    # Prompt first, then auto-formatted words appended.
    assert prompt == "Medical notes. AFib."
    assert hotwords is None


def test_compose_prompt_plus_words_for_faster_whisper():
    """faster-whisper takes the prompt text raw and routes words via the
    hotwords channel — both passed through unaltered."""
    prompt, hotwords = compose_prompt_for_backend("whisper", "Medical notes.",
                                                  ["AFib", "tachycardia"])
    assert prompt == "Medical notes."
    assert hotwords == "AFib tachycardia"


def test_compose_both_empty_returns_none():
    """When neither side has content, both fields are None so backends can
    skip the kwarg entirely instead of sending an empty string."""
    assert compose_prompt_for_backend("groq", None, None) == (None, None)
    assert compose_prompt_for_backend("groq", "", []) == (None, None)
    assert compose_prompt_for_backend("whisper", None, None) == (None, None)


# ── autodiscover_prompt_files ─────────────────────────────────────────────

def _ns(**kw):
    """Minimal argparse-like namespace: defaults to None for all four
    prompt/words attributes (what argparse fills when the flag is unset)."""
    defaults = dict(prompt=None, prompt_file=None, words=None, words_file=None)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_autodiscover_persists_default_paths_when_files_exist(monkeypatch, tmp_path):
    """The earlier bug: scribe was *loading* ~/.config/scribe/words.txt at
    startup but never writing the path back to `o`, so the tray menu's
    "Words file: …" label showed (none). Verify the path is persisted."""
    p = tmp_path / "prompt.txt"
    w = tmp_path / "words.txt"
    p.write_text("style hint")
    w.write_text("Tierney Comet")
    monkeypatch.setattr("scribe.app.DEFAULT_PROMPT_FILE", str(p))
    monkeypatch.setattr("scribe.app.DEFAULT_WORDS_FILE", str(w))

    o = _ns()
    autodiscover_prompt_files(o)

    assert o.prompt_file == str(p)
    assert o.words_file == str(w)


def test_autodiscover_skips_when_explicit_flag_passed(monkeypatch, tmp_path):
    """Passing --prompt-file /some/other or --prompt "..." suppresses the
    fallback — argparse-omitted (None) is the only trigger."""
    p = tmp_path / "prompt.txt"
    p.write_text("hi")
    monkeypatch.setattr("scribe.app.DEFAULT_PROMPT_FILE", str(p))

    o = _ns(prompt_file="/explicit/path.txt")
    autodiscover_prompt_files(o)
    assert o.prompt_file == "/explicit/path.txt"

    o = _ns(prompt="inline text")
    autodiscover_prompt_files(o)
    assert o.prompt_file is None


def test_autodiscover_skips_empty_string_explicit_suppression(monkeypatch, tmp_path):
    """``--prompt ""`` means "I explicitly want no prompt"; the `is None`
    check (not truthy) preserves that intent — should NOT auto-load."""
    p = tmp_path / "prompt.txt"
    p.write_text("hi")
    monkeypatch.setattr("scribe.app.DEFAULT_PROMPT_FILE", str(p))

    o = _ns(prompt="")
    autodiscover_prompt_files(o)
    assert o.prompt_file is None


def test_autodiscover_no_default_files_is_noop(monkeypatch, tmp_path):
    """When the default files don't exist on disk, the namespace is
    untouched — no error, just nothing to discover."""
    monkeypatch.setattr("scribe.app.DEFAULT_PROMPT_FILE", str(tmp_path / "nope.txt"))
    monkeypatch.setattr("scribe.app.DEFAULT_WORDS_FILE", str(tmp_path / "nada.txt"))

    o = _ns()
    autodiscover_prompt_files(o)
    assert o.prompt_file is None
    assert o.words_file is None
