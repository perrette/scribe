"""This module handles delivering text to the focused window.

Two public entry points:

- ``paste_via_clipboard(text, typer)`` — the main path. Writes ``text``
  to the clipboard, verifies the clipboard has caught up (defends against
  wl-copy's async propagation race on Wayland), then synthesizes Ctrl+V
  via the active typer. Used both per-chunk in live-streaming mode and
  once at end-of-recording in auto-paste mode.

- ``type_text(text, ...)`` — legacy per-character typing path. Kept for
  API consumers and debugging (``--typer X --keyboard``). The scribe
  recording loop no longer calls this; per-character typing through
  subprocess typers (eitype / wtype / ydotool) is fundamentally limited
  for non-ASCII text — see ``docs/roadmap-libei.md``.
"""
import time
import unidecode

_clipboard_configured = False


def configure_clipboard():
    """Route pyperclip through xclip instead of wl-copy on Wayland.

    pyperclip resolves to ``wl-copy`` on Wayland sessions. On compositors
    without a data-control protocol (GNOME < 47), wl-copy must create a
    temporary invisible window and grab keyboard focus to own the selection.
    That focus blip breaks paste-into-Electron-apps: the window gets focus
    back afterwards but the input field inside the webview does not, so the
    synthesized Ctrl+V lands nowhere. ``xclip`` owns the clipboard through
    XWayland with no focus change, and the compositor syncs the X and
    Wayland selections both ways, so Wayland-native apps still see the text.

    Idempotent; safe to call before every clipboard access. No-op outside
    Linux/Wayland or when xclip / XWayland is unavailable (pyperclip's own
    wl-copy backend remains in place).
    """
    global _clipboard_configured
    if _clipboard_configured:
        return
    _clipboard_configured = True
    import os
    import platform
    import shutil
    if platform.system() != "Linux" or not os.environ.get("WAYLAND_DISPLAY"):
        return
    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        import pyperclip
        pyperclip.set_clipboard("xclip")


def paste_via_clipboard(text, typer="auto", verify_iters=5, sleep_s=0.1):
    """Copy ``text`` to clipboard, verify ownership, synthesize Ctrl+V.

    On Wayland ``wl-copy`` is async — pyperclip.copy returns immediately
    but the new selection may not yet be the active clipboard owner when
    the paste keystroke fires. Re-write and verify with ``pyperclip.paste``
    until the clipboard reflects ``text``, then trigger the paste.

    ``verify_iters`` and ``sleep_s`` tune the worst-case wait:
      - End-of-recording auto-paste: defaults (5 × 100 ms, ~500 ms worst).
      - Per-chunk live mode: pass ``verify_iters=2, sleep_s=0.05`` (~100 ms).
    """
    import pyperclip
    from scribe.typers import pick_typer

    configure_clipboard()
    pyperclip.copy(text)
    for _ in range(verify_iters):
        time.sleep(sleep_s)
        try:
            if pyperclip.paste() == text:
                break
        except Exception:
            pass
        pyperclip.copy(text)
    pick_typer(typer if typer != "auto" else None).paste()


def type_text(text, interval=0, paste=False, ascii=False, typer="auto"):
    """Legacy per-character typing entry point. Kept for API consumers /
    debugging (``--typer X --keyboard`` from the CLI bypassing the live-paste
    refactor). The recording loop in scribe.app no longer routes through here.
    """
    from scribe.typers import pick_typer
    _typer = pick_typer(typer if typer != "auto" else None)

    if ascii:
        text = unidecode.unidecode(text)

    if paste:
        import pyperclip
        configure_clipboard()
        keep_state = pyperclip.paste()
        pyperclip.copy(text)
        _typer.paste()
        pyperclip.copy(keep_state)
        return

    if interval > 0:
        for c in text:
            _typer.type(c)
            time.sleep(interval)
    else:
        _typer.type(text)
