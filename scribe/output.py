"""Output sinks for the recording loop.

Each Output instance encapsulates "where the transcript goes": clipboard,
keystroke into the focused window, terminal stdout, or a file. The recording
loop calls ``on_chunk(chunk_text, fulltext)`` per emission and
``on_finalize(fulltext)`` once at end-of-recording.

Splitting this out lets the recording loop swap the sink mid-recording when
the tray menu toggles Output mode / Backend / Input mode — the loop just
rebuilds the Output via :func:`make_output` on the chunk boundary and the
new chunks land in the new destination.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class Output(ABC):
    """Sink for transcribed text.

    The recording loop calls :meth:`on_chunk` as each chunk arrives and
    :meth:`on_finalize` once at end-of-recording. Subclasses choose what
    those mean (live paste, append-to-file, batch-paste at end, etc.).
    """

    @abstractmethod
    def on_chunk(self, chunk_text: str, fulltext: str) -> None:
        """Called per chunk emission. ``chunk_text`` is the new fragment,
        ``fulltext`` is the running concatenation including this chunk."""

    @abstractmethod
    def on_finalize(self, fulltext: str) -> None:
        """End-of-recording delivery. Called once after the last chunk."""


class TerminalOutput(Output):
    """Print each chunk to stdout. The recording loop already prints chunks
    via ``print(result["text"])`` for diagnostics, so this Output is in
    practice a no-op sink — but explicit so the dispatch table is uniform.
    """

    def on_chunk(self, chunk_text: str, fulltext: str) -> None:
        # The recording loop already prints chunks; nothing to add here.
        # We keep the method intentional (not pass) so subclasses can be
        # introspected for "did anything happen?" diagnostics.
        return None

    def on_finalize(self, fulltext: str) -> None:
        return None


class ClipboardOutput(Output):
    """Copy the running transcript to the system clipboard as chunks arrive.

    Pure-clipboard mode (mode='clipboard'): the user pastes manually with
    Ctrl+V. The keyboard-paste sink (:class:`KeyboardOutput`) also writes to
    the clipboard but as a side-effect of synthesising Ctrl+V — that path
    lives in KeyboardOutput, not here.
    """

    def on_chunk(self, chunk_text: str, fulltext: str) -> None:
        import pyperclip
        pyperclip.copy(fulltext.strip())

    def on_finalize(self, fulltext: str) -> None:
        # Clipboard already has the running text after the last on_chunk.
        return None


class FileOutput(Output):
    """Append each chunk to ``path``.

    No trailing ``\\n`` is added — chunks are concatenated verbatim so the
    file mirrors what the keyboard/clipboard sinks deliver. Realtime
    backends emit per-word/per-delta chunks where a newline-per-chunk would
    produce one word per line; batch-streaming chunks are phrase-sized but
    are concatenated without separators too, matching the verbatim contract.
    Users who want phrase-per-line can post-process the file.

    The path is validated at construction by opening it once in append
    mode — bad path / unwritable dir raises immediately so the recording
    loop can fall back to the previous sink (see the live-switch handler
    in scribe.app).
    """

    def __init__(self, path: str):
        if not path:
            raise ValueError("FileOutput requires a non-empty path")
        # Validate openability up-front so the caller can swap to a
        # different sink before a chunk hits a broken path.
        with open(path, "a"):
            pass
        self.path = path

    def on_chunk(self, chunk_text: str, fulltext: str) -> None:
        with open(self.path, "a") as f:
            f.write(chunk_text)

    def on_finalize(self, fulltext: str) -> None:
        return None


class KeyboardOutput(Output):
    """Deliver the transcript to the focused window as keystrokes.

    Four sub-modes pinned at construction:

    - Streaming + paste (``is_streaming=True, type_direct=False``): each
      chunk is pasted via Ctrl+V (clipboard copy + synthesised paste).
    - Streaming + type-direct (``is_streaming=True, type_direct=True``):
      each chunk is typed character-by-character via the active typer.
    - Batch + paste (``is_streaming=False, type_direct=False``): the
      running text is copied to clipboard per-chunk; the final
      :meth:`on_finalize` synthesises Ctrl+V once with the full text.
    - Batch + type-direct (``is_streaming=False, type_direct=True``):
      :meth:`on_finalize` types the full text once.

    When wrapping a streaming backend, this sink also patches
    ``backend._coalesce_deltas`` to tell the backend whether per-word
    deltas need coalescing (paste mode) or can stream raw (type-direct).
    The patch is applied in ``__init__`` so rebuilding the Output on a
    live-switch re-applies the hint.
    """

    def __init__(self, typer_obj, type_direct: bool, is_streaming: bool,
                 *, backend_obj=None, typer_name: str = "auto"):
        # typer_obj is the resolved Typer instance — required only for
        # type-direct paths (live type per chunk / type at end). For
        # paste-based delivery the typer name is enough (paste_via_clipboard
        # does its own pick_typer).
        self.typer_obj = typer_obj
        self.type_direct = type_direct
        self.is_streaming = is_streaming
        self.typer_name = typer_name
        self.backend_obj = backend_obj

        # Tell streaming backends whether their output is about to hit the
        # clipboard-paste race or a direct-keystroke typer. The realtime
        # backend's per-token deltas only need coalescing in paste mode;
        # type-direct types each character synchronously and benefits from
        # raw per-delta emission for snappier UX. Set as a plain attribute —
        # backends that don't implement coalescing ignore it.
        do_live_paste = is_streaming and not type_direct
        if backend_obj is not None and not isinstance(backend_obj, str) and \
                hasattr(backend_obj, "_coalesce_deltas"):
            backend_obj._coalesce_deltas = do_live_paste

    def on_chunk(self, chunk_text: str, fulltext: str) -> None:
        import pyperclip
        if self.is_streaming and not self.type_direct:
            # Live paste-per-chunk: copy this chunk to clipboard and fire
            # Ctrl+V. Universal Unicode support (clipboard handles any
            # codepoint) and orthogonal to typer choice (Ctrl+V is the
            # same keystroke regardless of layout).
            from scribe.keyboard import paste_via_clipboard
            paste_via_clipboard(chunk_text, typer=self.typer_name,
                                verify_iters=2, sleep_s=0.05)
        elif self.is_streaming and self.type_direct:
            assert self.typer_obj is not None, \
                "KeyboardOutput type-direct mode requires a typer"
            self.typer_obj.type(chunk_text)
        else:
            # Batch (clip) mode: copy running text per chunk; paste/type
            # the final text once in on_finalize. The per-chunk copy
            # keeps the clipboard in sync if the user cancels mid-recording.
            pyperclip.copy(fulltext.strip())

    def on_finalize(self, fulltext: str) -> None:
        text = fulltext.strip()
        if not text:
            return
        if self.is_streaming:
            # Streaming paths delivered chunk-by-chunk during the loop;
            # nothing left to do at end-of-recording.
            return
        if self.type_direct:
            assert self.typer_obj is not None, \
                "KeyboardOutput type-direct mode requires a typer"
            self.typer_obj.type(text)
        else:
            from scribe.keyboard import paste_via_clipboard
            # Multi-chunk transcriptions (e.g. local whisper with silence-
            # splitting) called pyperclip.copy() many times during recording.
            # wl-copy is async on Wayland — paste_via_clipboard force-writes
            # the final text and polls until the clipboard reflects it before
            # triggering Ctrl+V.
            paste_via_clipboard(text, typer=self.typer_name)


def make_output(mode: str, *, typer: Optional[str], type_direct: bool,
                output_file: Optional[str], is_streaming: bool,
                backend_obj=None) -> Output:
    """Resolve ``(mode, typer, type_direct, output_file, is_streaming)``
    into the right Output subclass.

    ``mode`` values match the four-way Output radio in the tray:
    ``keystroke`` / ``clipboard`` / ``terminal`` / ``file``.

    Caller passes ``None`` for ``typer`` / ``output_file`` when not
    applicable; this factory enforces what's required per mode and raises
    ``ValueError`` otherwise so the recording-loop's live-switch handler
    can fall back to the previous Output.
    """
    if mode not in ("keystroke", "clipboard", "terminal", "file"):
        raise ValueError(
            f"Unknown mode {mode!r} (expected keystroke|clipboard|terminal|file)"
        )

    if mode == "terminal":
        return TerminalOutput()

    if mode == "clipboard":
        return ClipboardOutput()

    if mode == "file":
        if not output_file:
            raise ValueError(
                "mode='file' requires --output-file (or set o.output_file "
                "before switching the Output radio)."
            )
        return FileOutput(output_file)

    # mode == "keystroke"
    type_direct = bool(type_direct)
    if type_direct:
        from scribe.typers import pick_typer
        typer_obj = pick_typer(typer if typer and typer != "auto" else None)
    else:
        typer_obj = None
    return KeyboardOutput(
        typer_obj=typer_obj,
        type_direct=type_direct,
        is_streaming=is_streaming,
        backend_obj=backend_obj,
        typer_name=typer or "auto",
    )
