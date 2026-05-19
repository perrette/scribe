from __future__ import annotations

import logging
import os
import shutil
import subprocess

from scribe.typers import TYPERS
from scribe.typers.base import Typer


class WtypeTyper:
    name = "wtype"

    def available(self) -> bool:
        if shutil.which("wtype") is None:
            return False
        if not os.environ.get("WAYLAND_DISPLAY"):
            return False
        if not os.environ.get("XDG_RUNTIME_DIR"):
            return False
        # wtype speaks zwp_virtual_keyboard_v1, which only wlroots-based
        # compositors implement. GNOME/Mutter, KDE/KWin and Unity don't —
        # invoking wtype there fails at runtime with "Compositor does not
        # support the virtual keyboard protocol".
        desktop = (
            os.environ.get("XDG_CURRENT_DESKTOP", "")
            + ":" + os.environ.get("XDG_SESSION_DESKTOP", "")
        ).lower()
        if any(x in desktop for x in ("gnome", "kde", "plasma", "unity")):
            return False
        return True

    def type(self, text: str) -> None:
        try:
            subprocess.run(["wtype", "--", text], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            # wtype refuses chars not in the active xkb layout. Retry with
            # diacritics stripped so streaming-keyboard mode degrades
            # gracefully on French / German / etc. text.
            import unidecode  # local import to keep cold-start cheap
            ascii_text = unidecode.unidecode(text)
            if ascii_text == text:
                raise RuntimeError(
                    f"wtype failed: {e.stderr.decode(errors='replace')}"
                ) from e
            logging.warning(
                f"wtype cannot type {text!r}; retrying as ASCII {ascii_text!r}"
            )
            try:
                subprocess.run(
                    ["wtype", "--", ascii_text], check=True, capture_output=True
                )
            except subprocess.CalledProcessError as e2:
                raise RuntimeError(
                    f"wtype failed: {e2.stderr.decode(errors='replace')}"
                ) from e2

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
