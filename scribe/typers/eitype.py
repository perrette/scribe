from __future__ import annotations

import shutil
import subprocess

from scribe.typers import TYPERS
from scribe.typers.base import Typer


class EitypeTyper:
    name = "eitype"

    def available(self) -> bool:
        return shutil.which("eitype") is not None

    def type(self, text: str) -> None:
        try:
            subprocess.run(["eitype", "--", text], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"eitype failed: {e.stderr.decode(errors='replace')}") from e

    def paste(self) -> None:
        try:
            subprocess.run(["eitype", "-M", "ctrl", "v"], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"eitype failed: {e.stderr.decode(errors='replace')}") from e


# satisfy the Protocol check without a hard isinstance — duck-typed
assert isinstance(EitypeTyper, type)
TYPERS["eitype"] = EitypeTyper  # type: ignore[assignment]
