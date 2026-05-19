import os
import platform
import logging
import unidecode
from pynput.keyboard import Controller, Key

from scribe.typers import TYPERS

_TYPE_ERRORS = (KeyError, Controller.InvalidKeyException, Controller.InvalidCharacterException)


class PynputTyper:
    name = "pynput"

    def __init__(self):
        self._keyboard = Controller()

    def available(self) -> bool:
        sys = platform.system()
        if sys in ("Darwin", "Windows"):
            return True
        return bool(os.environ.get("DISPLAY"))

    def type(self, text: str) -> None:
        try:
            self._keyboard.type(text)
        except _TYPE_ERRORS:
            asciitext = unidecode.unidecode(text)
            logging.warning(f"Cannot type {text!r} -> convert to {asciitext!r}")
            try:
                self._keyboard.type(asciitext)
            except _TYPE_ERRORS:
                logging.warning(f"Skipping untypable text {text!r}")

    def paste(self) -> None:
        os_name = platform.system()
        if os_name == "Darwin":
            with self._keyboard.pressed(Key.cmd):
                self._keyboard.press('v')
                self._keyboard.release('v')
        else:
            self._keyboard.press(Key.ctrl)
            self._keyboard.press('v')
            self._keyboard.release('v')
            self._keyboard.release(Key.ctrl)


TYPERS["pynput"] = PynputTyper
