from __future__ import annotations

import os
import shutil
import subprocess

from scribe.typers import TYPERS
from scribe.typers.base import Typer


class WtypeTyper:
    name = "wtype"

    def available(self) -> bool:
        return (
            shutil.which("wtype") is not None
            and bool(os.environ.get("WAYLAND_DISPLAY"))
            and bool(os.environ.get("XDG_RUNTIME_DIR"))
        )

    def type(self, text: str) -> None:
        try:
            subprocess.run(["wtype", "--", text], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"wtype failed: {e.stderr.decode(errors='replace')}") from e

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
