from typing import Protocol, runtime_checkable


@runtime_checkable
class Typer(Protocol):
    name: str

    def available(self) -> bool: ...
    def type(self, text: str) -> None: ...
    def paste(self) -> None: ...
