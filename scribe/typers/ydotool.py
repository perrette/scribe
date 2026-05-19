from __future__ import annotations

import os
import shutil
import subprocess

from scribe.typers import TYPERS
from scribe.typers.base import Typer


class YdotoolTyper:
    name = "ydotool"

    def available(self) -> bool:
        if shutil.which("ydotool") is None:
            return False
        uid = os.getuid()
        candidates = [
            os.environ.get("YDOTOOL_SOCKET"),
            os.path.join(os.environ["XDG_RUNTIME_DIR"], ".ydotool_socket")
            if os.environ.get("XDG_RUNTIME_DIR")
            else None,
            f"/run/user/{uid}/.ydotool_socket",
            "/tmp/.ydotool_socket",
        ]
        return any(p and os.path.exists(p) for p in candidates)

    def type(self, text: str) -> None:
        try:
            subprocess.run(["ydotool", "type", "--", text], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ydotool failed: {e.stderr.decode(errors='replace')}") from e

    def paste(self) -> None:
        try:
            subprocess.run(
                ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ydotool failed: {e.stderr.decode(errors='replace')}") from e


TYPERS["ydotool"] = YdotoolTyper  # type: ignore[assignment]
