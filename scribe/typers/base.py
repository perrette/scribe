from typing import Protocol, runtime_checkable


@runtime_checkable
class Typer(Protocol):
    name: str

    def compatible(self) -> bool:
        """True iff the host OS / session could *in principle* run this backend
        (ignores setup). False means the backend is structurally impossible
        here — e.g. ydotool on macOS, wtype on GNOME. Used by the menu to
        hide incompatible rows entirely. Distinct from ``available()``, which
        further requires binaries / daemons / sockets to be set up."""
        ...

    def available(self) -> bool: ...
    def type(self, text: str) -> None: ...
    def paste(self) -> None: ...
