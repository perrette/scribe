import re
from typing import Callable, Protocol, Tuple, Type, runtime_checkable

import unidecode

# Split a string into maximal runs of ASCII plus each individual non-ASCII
# character, preserving order: "café là" -> ["caf", "é", " l", "à", ""]-ish.
_ASCII_RUN_OR_CHAR = re.compile(r"[\x00-\x7f]+|[^\x00-\x7f]")


def type_ascii_safe(
    emit: Callable[[str], None],
    text: str,
    errors: Tuple[Type[BaseException], ...],
) -> None:
    """Type ``text`` via ``emit`` while degrading untypable characters to ASCII
    **without re-emitting already-typed text**.

    Keystroke typers (wtype / eitype / pynput) emit left-to-right and abort
    mid-string when the active xkb layout can't produce a character — but the
    prefix is already out by then. The naive recovery (retry the whole string
    transliterated to ASCII) re-types that prefix, so a chunk like
    "le message dicté" lands as "le message dict" + "le message dicte" — the
    duplicated-prefix bug.

    Instead, emit maximal ASCII runs in one call each (always layout-typeable)
    and, for each individual non-ASCII character, try it raw and fall back to
    its ASCII transliteration on ``errors``. Unicode survives on layouts that
    support it; the rest degrades per-character with no duplication. Failures
    on ASCII content are genuine (compositor / daemon) and propagate.
    """
    for token in _ASCII_RUN_OR_CHAR.findall(text):
        if token.isascii():
            # Always layout-typeable; a failure here is genuine (compositor /
            # daemon down) — let it propagate.
            emit(token)
        else:
            try:
                emit(token)
            except errors:
                try:
                    emit(unidecode.unidecode(token))
                except errors:
                    # Even the transliteration is unrenderable — skip this
                    # one char rather than abort the whole transcript.
                    pass


@runtime_checkable
class Typer(Protocol):
    name: str

    def compatible(self) -> bool:
        """True iff the host OS / session could *in principle* run this backend
        (ignores setup). False means the backend is structurally impossible
        here — e.g. ydotool on macOS, wtype on GNOME. Used by the menu to
        hide incompatible rows entirely. Distinct from ``available()``, which
        further requires binaries / daemons / sockets to be set up."""
        ...

    def available(self) -> bool: ...
    def type(self, text: str) -> None: ...
    def paste(self) -> None: ...
