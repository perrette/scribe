import shutil

# Function to clear the terminal line
def clear_line():
    # Get terminal width
    terminal_width = shutil.get_terminal_size().columns
    print("\r" + " " * terminal_width, end="")  # Clear the line
    print("\r", end="")  # Return cursor to the beginning of the line


def print_partial(msg):
    # Get terminal width
    terminal_width = shutil.get_terminal_size().columns
    start = max(0, len(msg) + 7 - terminal_width)
    print(f"\r[...] {msg[start:]}", end="")