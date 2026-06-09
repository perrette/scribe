from __future__ import annotations

import logging
import os
import shutil
import subprocess

import unidecode

from scribe.typers import TYPERS
from scribe.typers.base import Typer


class WtypeTyper:
    name = "wtype"

    def compatible(self) -> bool:
        """Linux Wayland on a wlroots-based compositor (Sway, Hyprland, …).
        wtype speaks zwp_virtual_keyboard_v1, which GNOME/Mutter, KDE/KWin
        and Unity have explicitly refused to implement."""
        import platform as _platform
        if _platform.system() != "Linux":
            return False
        if not os.environ.get("WAYLAND_DISPLAY"):
            return False
        desktop = (
            os.environ.get("XDG_CURRENT_DESKTOP", "")
            + ":" + os.environ.get("XDG_SESSION_DESKTOP", "")
        ).lower()
        if any(x in desktop for x in ("gnome", "kde", "plasma", "unity")):
            return False
        return True

    def available(self) -> bool:
        if not self.compatible():
            return False
        if shutil.which("wtype") is None:
            return False
        if not os.environ.get("XDG_RUNTIME_DIR"):
            return False
        return True

    def _emit(self, text: str) -> None:
        try:
            subprocess.run(["wtype", "--", text], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"wtype failed: {e.stderr.decode(errors='replace')}"
            ) from e

    def type(self, text: str) -> None:
        # wtype refuses chars not in the active xkb layout, aborting mid-string
        # after emitting the typeable prefix. Recovering by typing the rest in
        # pieces would fire one short-lived virtual keyboard per piece, and
        # Electron/Wayland apps (e.g. VS Code) silently drop input from those
        # rapid keyboards even though terminals tolerate it. So transliterate
        # non-ASCII to ASCII up front and emit the whole chunk in a SINGLE
        # call: an all-ASCII string can't fail mid-string, so there is no
        # partial prefix to re-type (the duplicated-prefix bug) and keystrokes
        # keep landing in every window. Use auto-paste mode for full Unicode.
        if not text.isascii():
            ascii_text = unidecode.unidecode(text)
            logging.warning(
                f"wtype cannot reliably type non-ASCII via the active layout; "
                f"using {ascii_text!r} instead of {text!r} "
                f"(switch to auto-paste mode for full Unicode)"
            )
            text = ascii_text
        self._emit(text)

    def paste(self) -> None:
        try:
            subprocess.run(
                ["wtype", "-M", "ctrl", "-P", "v", "-p", "v", "-m", "ctrl"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"wtype failed: {e.stderr.decode(errors='replace')}") from e


assert isinstance(WtypeTyper, type)
TYPERS["wtype"] = WtypeTyper  # type: ignore[assignment]
