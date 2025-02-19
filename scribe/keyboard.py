"""This module handles typing characters as if they were typed on a keyboard.
"""
try:
    # import pyautogui
    from pynput.keyboard import Controller

except ImportError:
    print("Please install pynput to use the keyboard feature.")
    raise

# Create a keyboard controller
keyboard = Controller()

def type_text(text, interval=0):
    # Simulate typing a string
    # import subprocess
    # subprocess.run(["ydotool", "type", text])
    keyboard.type(text)