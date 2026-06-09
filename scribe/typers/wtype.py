from __future__ import annotations

import os
import shutil
import subprocess

from scribe.typers import TYPERS
from scribe.typers.base import Typer, type_ascii_safe


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
        # wtype refuses chars not in the active xkb layout, aborting AFTER
        # emitting the typeable prefix. type_ascii_safe types ASCII runs whole
        # and falls back to ASCII per non-typeable char, so French / German /
        # etc. text degrades gracefully without re-emitting the prefix (the
        # duplicated-prefix bug a naive whole-string ASCII retry produced).
        type_ascii_safe(self._emit, text, (RuntimeError,))

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
