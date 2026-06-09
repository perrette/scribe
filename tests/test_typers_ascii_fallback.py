"""Regression tests for the duplicated-prefix bug in keystroke typers.

Keystroke typers emit left-to-right and abort mid-string when the active xkb
layout can't produce a character -- but the typeable prefix is already out by
then. The old recovery (retry the whole string transliterated to ASCII)
re-typed that prefix, so a chunk like "le message dicte" (with an accent)
landed as "le message dict" plus "le message dicte".

type_ascii_safe (used by the in-process pynput typer) types maximal ASCII runs
whole and degrades only the individual untypable characters, so the prefix is
never re-emitted. The subprocess typers (wtype / eitype) avoid the same bug by
transliterating up front and emitting once per chunk -- see their own modules.
"""
import pytest

from scribe.typers.base import type_ascii_safe


class LayoutError(Exception):
    """Stand-in for the per-typer 'char not in layout' failure."""


def _record(can_type_unicode):
    """Return (typed_list, emit) where emit() appends typeable tokens and
    raises LayoutError on a token the fake layout can't produce."""
    typed = []

    def emit(s):
        if not s.isascii() and not can_type_unicode(s):
            raise LayoutError(s)
        typed.append(s)

    return typed, emit


def test_no_unicode_layout_does_not_duplicate_prefix():
    typed, emit = _record(lambda s: False)
    type_ascii_safe(emit, "le message dicté est écrit", (LayoutError,))
    out = "".join(typed)
    assert out == "le message dicte est ecrit"
    # The original bug re-typed everything up to the first accent.
    assert out.count("le message") == 1


def test_unicode_capable_layout_preserves_accents():
    typed, emit = _record(lambda s: True)
    text = "café là"
    type_ascii_safe(emit, text, (LayoutError,))
    assert "".join(typed) == text


def test_partial_layout_degrades_only_untypable_chars():
    # Only the typeable accent stays; the other falls back to ASCII.
    typeable = "é"
    typed, emit = _record(lambda s: s == typeable)
    type_ascii_safe(emit, "aé bà", (LayoutError,))
    assert "".join(typed) == "aé ba"


def test_ascii_failures_propagate():
    # A failure on ASCII content is genuine (compositor/daemon down).
    def emit(s):
        raise LayoutError(s)

    with pytest.raises(LayoutError):
        type_ascii_safe(emit, "plain ascii", (LayoutError,))


def test_unrenderable_char_is_skipped_not_fatal():
    # Non-ASCII char untypable raw AND whose transliteration ('e') is also
    # rejected -> skip it, but the surrounding ASCII still lands.
    typed = []

    def emit(s):
        if not s.isascii() or s == "e":
            raise LayoutError(s)
        typed.append(s)

    type_ascii_safe(emit, "xéy", (LayoutError,))
    assert "".join(typed) == "xy"
