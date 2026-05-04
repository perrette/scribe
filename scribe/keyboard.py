"""This module handles typing characters as if they were typed on a keyboard.
"""
import platform
import time
import unidecode
import logging

try:
    # import pyautogui
    from pynput.keyboard import Controller, Key

except ImportError:
    print("Please install pynput to use the keyboard feature.")
    raise

# Create a keyboard controller
keyboard = Controller()

def paste_text():
    """This does not work with the uinput backend
    """
    os_name = platform.system()

    if os_name == "Darwin":  # macOS
        with keyboard.pressed(Key.cmd):
            keyboard.press('v')
            keyboard.release('v')

    else:  # Windows and Linux
        keyboard.press(Key.ctrl)
        keyboard.press('v')
        keyboard.release('v')
        keyboard.release(Key.ctrl)

_TYPE_ERRORS = (KeyError, Controller.InvalidKeyException, Controller.InvalidCharacterException)

def safe_type_text(text):
    """Some characters cannot be synthesized by the active pynput backend
    (uinput raises KeyError; xorg raises InvalidKeyException for non-Latin
    scripts like CJK; keyboard.type() wraps it as InvalidCharacterException).
    Fall back to unidecode, then to skipping."""
    try:
        keyboard.type(text)
    except _TYPE_ERRORS:
        asciitext = unidecode.unidecode(text)
        logging.warning(f"Cannot type {text!r} -> convert to {asciitext!r}")
        try:
            keyboard.type(asciitext)
        except _TYPE_ERRORS:
            logging.warning(f"Skipping untypable text {text!r}")

def type_text(text, interval=0, paste=False, ascii=False):
    # Simulate typing a string
    # import subprocess
    # subprocess.run(["ydotool", "type", text])

    if ascii:
        text = unidecode.unidecode(text)

    if paste:
        import pyperclip
        keep_state = pyperclip.paste()
        pyperclip.copy(text)
        paste_text()
        pyperclip.copy(keep_state)
        return

    if interval > 0:
        for c in text:
            # keyboard.type(c)
            safe_type_text(c)
            time.sleep(interval)
    else:
        # keyboard.type(text)
        safe_type_text(text)
