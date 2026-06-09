import os
import platform
from pynput.keyboard import Controller, Key

from scribe.typers import TYPERS
from scribe.typers.base import type_ascii_safe

_TYPE_ERRORS = (KeyError, Controller.InvalidKeyException, Controller.InvalidCharacterException)


class PynputTyper:
    name = "pynput"

    def __init__(self):
        self._keyboard = Controller()

    def compatible(self) -> bool:
        """OS/environment supports this backend at all (ignores setup)."""
        sys = platform.system()
        if sys in ("Darwin", "Windows"):
            return True
        # Linux: compatible iff an X server is reachable (X11 or XWayland).
        return bool(os.environ.get("DISPLAY"))

    def available(self) -> bool:
        return self.compatible()

    def caveat(self) -> str | None:
        """Context-aware qualifier for menu display. None means no caveat."""
        # pynput's Linux backend uses XTest. On a Wayland session it still
        # connects (because XWayland sets $DISPLAY), but the events only
        # reach XWayland-hosted apps — native Wayland clients drop them.
        if platform.system() == "Linux" and (
            os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("XDG_SESSION_TYPE") == "wayland"
        ):
            return "XWayland apps only"
        return None

    def type(self, text: str) -> None:
        # _keyboard.type() emits left-to-right and raises mid-string on a char
        # the platform can't produce, leaving the prefix already typed. Retrying
        # the whole transliterated string (the old behaviour) re-typed that
        # prefix — the duplicated-prefix bug. type_ascii_safe emits ASCII runs
        # whole and degrades only the individual untypable chars to ASCII.
        type_ascii_safe(self._keyboard.type, text, _TYPE_ERRORS)

    def paste(self) -> None:
        os_name = platform.system()
        if os_name == "Darwin":
            with self._keyboard.pressed(Key.cmd):
                self._keyboard.press('v')
                self._keyboard.release('v')
        else:
            self._keyboard.press(Key.ctrl)
            self._keyboard.press('v')
            self._keyboard.release('v')
            self._keyboard.release(Key.ctrl)


TYPERS["pynput"] = PynputTyper
