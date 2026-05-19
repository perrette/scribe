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

    def type(self, text: str) -> None:
        try:
            subprocess.run(["eitype", "--", text], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            # eitype refuses chars not in the active xkb layout (and pops
            # an error dialog). Retry the chunk with diacritics stripped
            # so streaming-keyboard mode degrades gracefully on French /
            # German / etc. text instead of breaking the recording.
            ascii_text = unidecode.unidecode(text)
            if ascii_text == text:
                raise RuntimeError(
                    f"eitype failed: {e.stderr.decode(errors='replace')}"
                ) from e
            logging.warning(
                f"eitype cannot type {text!r}; retrying as ASCII {ascii_text!r}"
            )
            try:
                subprocess.run(
                    ["eitype", "--", ascii_text], check=True, capture_output=True
                )
            except subprocess.CalledProcessError as e2:
                raise RuntimeError(
                    f"eitype failed: {e2.stderr.decode(errors='replace')}"
                ) from e2

    def paste(self) -> None:
        try:
            subprocess.run(["eitype", "-M", "ctrl", "v"], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"eitype failed: {e.stderr.decode(errors='replace')}") from e


# satisfy the Protocol check without a hard isinstance — duck-typed
assert isinstance(EitypeTyper, type)
TYPERS["eitype"] = EitypeTyper  # type: ignore[assignment]
