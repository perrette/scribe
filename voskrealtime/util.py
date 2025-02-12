import os
import tqdm
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


def download_model(url, data_folder):
    import requests
    import zipfile
    import io

    os.makedirs(data_folder, exist_ok=True)

    print(f"Downloading model from {url}...")
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024  # 1 Kibibyte
    t = tqdm.tqdm(total=total_size, unit='iB', unit_scale=True)

    with io.BytesIO() as temp_file:
        for data in response.iter_content(block_size):
            t.update(len(data))
            temp_file.write(data)
        t.close()
        temp_file.seek(0)
        with zipfile.ZipFile(temp_file) as z:
            z.extractall(data_folder)

    print(f"Model downloaded and unpacked to {data_folder}")
