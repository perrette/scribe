from __future__ import annotations

import logging
import shutil
import subprocess

import unidecode

from scribe.typers import TYPERS
from scribe.typers.base import Typer


class EitypeTyper:
    name = "eitype"

    def compatible(self) -> bool:
        """Linux Wayland session; libei is a Wayland-specific protocol."""
        import platform as _platform
        import os as _os
        if _platform.system() != "Linux":
            return False
        return bool(
            _os.environ.get("WAYLAND_DISPLAY")
            or _os.environ.get("XDG_SESSION_TYPE") == "wayland"
        )

    def available(self) -> bool:
        return self.compatible() and shutil.which("eitype") is not None

    def _emit(self, text: str) -> None:
        try:
            subprocess.run(["eitype", "--", text], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"eitype failed: {e.stderr.decode(errors='replace')}"
            ) from e

    def type(self, text: str) -> None:
        # eitype refuses chars not in the active xkb layout (and pops an error
        # dialog), aborting mid-string after emitting the typeable prefix.
        # Recovering by typing the rest in pieces would fire one short-lived
        # virtual keyboard per piece, and Electron/Wayland apps (e.g. VS Code)
        # silently drop input from those rapid keyboards even though terminals
        # tolerate it. So transliterate non-ASCII to ASCII up front and emit
        # the whole chunk in a SINGLE call: an all-ASCII string can't fail
        # mid-string, so there is no partial prefix to re-type (the duplicated-
        # prefix bug) and keystrokes keep landing in every window. Use auto-
        # paste mode for full Unicode.
        if not text.isascii():
            ascii_text = unidecode.unidecode(text)
            logging.warning(
                f"eitype cannot reliably type non-ASCII via the active layout; "
                f"using {ascii_text!r} instead of {text!r} "
                f"(switch to auto-paste mode for full Unicode)"
            )
            text = ascii_text
        self._emit(text)

    def paste(self) -> None:
        try:
            subprocess.run(["eitype", "-M", "ctrl", "v"], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"eitype failed: {e.stderr.decode(errors='replace')}") from e


# satisfy the Protocol check without a hard isinstance — duck-typed
assert isinstance(EitypeTyper, type)
TYPERS["eitype"] = EitypeTyper  # type: ignore[assignment]
