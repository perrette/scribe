from __future__ import annotations

import logging
import os
import shutil
import subprocess

import unidecode

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
        # ydotool maps Unicode codepoints to keycodes via the current xkb
        # layout. Chars not in the layout silently truncate mid-string —
        # there is no error to catch. Pre-translate to ASCII so output is
        # at least predictable; the user can switch to auto-paste mode
        # (clipboard + Ctrl+V) for lossless Unicode.
        if not text.isascii():
            ascii_text = unidecode.unidecode(text)
            logging.warning(
                f"ydotool cannot type non-ASCII reliably; using {ascii_text!r} "
                f"instead of {text!r} (switch to auto-paste mode for full Unicode)"
            )
            text = ascii_text
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
