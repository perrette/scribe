"""This module handles typing characters as if they were typed on a keyboard.
"""
try:
    import pyautogui
except ImportError:
    print("Please install pyautogui to use the keyboard feature.")
    print("Alternatively specify [keyboard] optional dependency to voskrealtime, e.g. `pip install -e .[keyboard]`")
    raise
    # exit(1)

try:
    import pyperclip
    PYPERCLIP = True
except ImportError:
    print("Please install pyperclip to use the keyboard feature with non-ascii characters.")
    PYPERCLIP = False

def type_text_with_clipboard(text):
    assert PYPERCLIP, "pyperclip is not installed"
    pyperclip.copy(text)
    pyautogui.hotkey('ctrl', 'v')

def type_text(text, interval=0):
    if PYPERCLIP:
        type_text_with_clipboard(text)
    else:
        pyautogui.write(text, interval=interval)