from __future__ import annotations

from scribe.typers.base import Typer

TYPERS: dict[str, type[Typer]] = {}
_PROBE_ORDER: list[str] = ["eitype", "pynput"]


def pick_typer(name: str | None = None) -> Typer:
    """Return the typer matching `name`, or probe `_PROBE_ORDER` if name is None."""
    import importlib

    if name is not None:
        if name not in TYPERS:
            try:
                importlib.import_module(f"scribe.typers.{name}")
            except ImportError:
                pass
        if name not in TYPERS:
            raise KeyError(f"Typer {name!r} not registered")
        t = TYPERS[name]()
        if not t.available():
            raise RuntimeError(f"Typer {name!r} is not available in this environment")
        return t

    for n in _PROBE_ORDER:
        if n not in TYPERS:
            try:
                importlib.import_module(f"scribe.typers.{n}")
            except ImportError:
                continue
        if n not in TYPERS:
            continue
        t = TYPERS[n]()
        if t.available():
            return t

    raise RuntimeError("No typer is available in this environment")


import scribe.typers.pynput as _pynput_mod  # noqa: E402, F401  registers PynputTyper
import scribe.typers.eitype as _eitype_mod  # noqa: E402, F401  registers EitypeTyper
