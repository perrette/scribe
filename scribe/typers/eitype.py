from __future__ import annotations

import shutil
import subprocess

from scribe.typers import TYPERS
from scribe.typers.base import Typer, type_ascii_safe


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
        # dialog), aborting AFTER emitting the typeable prefix. type_ascii_safe
        # types ASCII runs whole and falls back to ASCII per non-typeable char,
        # so French / German / etc. text degrades gracefully without re-emitting
        # the prefix (the duplicated-prefix bug a whole-string ASCII retry made).
        type_ascii_safe(self._emit, text, (RuntimeError,))

    def paste(self) -> None:
        try:
            subprocess.run(["eitype", "-M", "ctrl", "v"], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"eitype failed: {e.stderr.decode(errors='replace')}") from e


# satisfy the Protocol check without a hard isinstance — duck-typed
assert isinstance(EitypeTyper, type)
TYPERS["eitype"] = EitypeTyper  # type: ignore[assignment]
