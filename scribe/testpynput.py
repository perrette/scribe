import subprocess

def type_text(text):
    subprocess.run(["ydotool", "type", text])

# Example usage
type_text("Hello, World!")


import pyautogui
import time

# Simulate typing a string
pyautogui.write('Hello, pyautogui!', interval=0.1)



# # Simulate pressing and releasing the Enter key
# pyautogui.press('enter')

# # Simulate pressing and releasing the 'A' key
# pyautogui.press('a')

# # Simulate a hotkey combination (e.g., Ctrl+C)
# pyautogui.hotkey('ctrl', 'c')

# Hello, World!

# # import os
# # import subprocess
# # from evdev import UInput, ecodes as e
# # # Function to create and initialize a virtual keyboard
# # def create_virtual_keyboard():
# #     capabilities = {
# #         e.EV_KEY: [e.KEY_A, e.KEY_B, e.KEY_C, e.KEY_1, e.KEY_2, e.KEY_3]
# #     }
# #     return UInput(capabilities)
# # # Function to send a keystroke
# # def send_keystroke(virtual_keyboard, key):
# #     virtual_keyboard.write(e.EV_KEY, key, 1)  # Key down
# #     virtual_keyboard.write(e.EV_KEY, key, 0)  # Key up
# #     virtual_keyboard.syn()

# # # Main script execution
# # if __name__ == "__main__":
# #     try:
# #         vk = create_virtual_keyboard()
# #         print("Virtual keyboard initialized.")
# #         send_keystroke(vk, e.KEY_A)  # Sends the 'A' key
# #         send_keystroke(vk, e.KEY_B)  # Sends the 'B' key
# #     finally:
# #         vk.close()
# #         print("Virtual keyboard closed.")


# import os
# import subprocess
# from evdev import UInput, ecodes as e

# # Function to create and initialize a virtual keyboard
# def create_virtual_keyboard():
#     capabilities = {
#         e.EV_KEY: [e.KEY_A, e.KEY_B, e.KEY_C, e.KEY_1, e.KEY_2, e.KEY_3]
#     }
#     try:
#         ui = UInput(capabilities, name="virtual-keyboard")
#         print("Virtual keyboard created successfully.")
#         return ui
#     except Exception as ex:
#         print(f"Failed to create virtual keyboard: {ex}")
#         return None

# # Function to send a keystroke
# def send_keystroke(virtual_keyboard, key):
#     try:
#         virtual_keyboard.write(e.EV_KEY, key, 1)  # Key down
#         virtual_keyboard.write(e.EV_KEY, key, 0)  # Key up
#         virtual_keyboard.syn()
#         print(f"Sent keystroke: {key}")
#     except Exception as ex:
#         print(f"Failed to send keystroke: {ex}")

# # Main script execution
# if __name__ == "__main__":
#     vk = create_virtual_keyboard()
#     if vk:
#         try:
#             send_keystroke(vk, e.KEY_A)  # Sends the 'A' key
#             send_keystroke(vk, e.KEY_B)  # Sends the 'B' key
#         finally:
#             vk.close()
#             print("Virtual keyboard closed.")


from pynput.keyboard import Controller, Key
import time

# Create a keyboard controller
keyboard = Controller()

# Simulate typing a string
keyboard.type("Hello, World!")

# Simulate pressing and releasing a key
keyboard.press(Key.enter)
keyboard.release(Key.enter)

# Simulate pressing and releasing the 'A' key
keyboard.press('a')
keyboard.release('a')

# Simulate pressing and releasing the 'Ctrl' key
with keyboard.pressed(Key.ctrl):
    keyboard.press('c')
    keyboard.release('c')



# import time
# import subprocess

# def send_key_event(event_device, key_code):
#     # Press the key
#     subprocess.run(["sudo", "evemu-event", event_device, "--type", "EV_KEY", "--code", key_code, "--value", "1", "--sync"])
#     # Release the key
#     subprocess.run(["sudo", "evemu-event", event_device, "--type", "EV_KEY", "--code", key_code, "--value", "0", "--sync"])

# # Example usage
# event_device = "/dev/input/event3"  # Your keyboard device
# send_key_event(event_device, "KEY_A")

# for letter in "Hello, World!":
#     if letter:
#         if letter == " ":
#             send_key_event(event_device, "KEY_SPACE")
#         elif letter == ",":
#             send_key_event(event_device, "KEY_COMMA")
#         elif letter == "!":
#             send_key_event(event_device, "KEY_1")
#         else:
#             send_key_event(event_device, f"KEY_{letter.upper()}")
#     time.sleep(0.1)