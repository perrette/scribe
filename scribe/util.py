import os
import re
import tqdm
import shutil
from functools import partial


class bcolors:
    # https://stackoverflow.com/a/287944/2192272
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def strip_colors(s):
    for name, c in vars(bcolors).items():
        if name.startswith("_"):
            continue
        s = s.replace(c, '')
    return s


def ansi_link(uri, label=None):
    """https://stackoverflow.com/a/71309268/2192272
    """
    if label is None:
        label = uri
    parameters = ''

    # OSC 8 ; params ; URI ST <name> OSC 8 ;; ST
    escape_mask = '\033]8;{};{}\033\\{}\033]8;;\033\\'

    return escape_mask.format(parameters, uri, label)

def colored(text, color):
    if hasattr(bcolors, color):
        color = getattr(bcolors, color)
    return f"{color}{text}{bcolors.ENDC}"


ANSI_LINK_RE = re.compile(r'(?P<ansi_sequence>\033]8;(?P<parameter>.*?);(?P<uri>.*?)\033\\(?P<label>.*?)\033]8;;\033\\)')

def strip_ansi_link(s):
    for m in ANSI_LINK_RE.findall(s):
        s = s.replace(m[0], m[3])
    return s


def strip_all(s):
    s = strip_colors(s)
    s = strip_ansi_link(s)
    return s


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

def check_status_code(status_code):
    if 200 <= status_code < 300:
        return True
    else:
        return False

def download_model(url, data_folder):
    import requests
    import zipfile
    import io

    os.makedirs(data_folder, exist_ok=True)

    print(f"Downloading model from {url}...")
    response = requests.get(url, stream=True)

    # check the URL was correct:
    if not check_status_code(response.status_code):
        raise RuntimeError(f"Model download failed with error {response.status_code}")

    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024  # 1 Kibibyte
    t = tqdm.tqdm(total=total_size, unit='iB', unit_scale=True)

    with io.BytesIO() as temp_file:
        for data in response.iter_content(block_size):
            t.update(len(data))
            temp_file.write(data)
        t.close()
        temp_file.seek(0)

        # check the file was downloaded correctly
        if total_size != 0 and t.n != total_size:
            raise RuntimeError(f"Model download size is 0 or less than stated size")

        with zipfile.ZipFile(temp_file) as z:
            z.extractall(data_folder)

    print(f"Model downloaded and unpacked to {data_folder}")


def format_choice(enum, default=None, unavailable=None):
    i, value = enum
    if type(value) in [tuple, list]:
        value_str = f" {value[0]} ({' | '.join(value[1:])})"
    else:
        value_str = value

    if (default is not None and value == default) or (default is None and i == 0):
        return f'  ' + colored(f'({i+1}) {value_str} [Press Enter]', 'BOLD')
    elif unavailable and value in unavailable:
        return f'  ' + colored(f'{" "} {value_str} -> unavailable !!', 'FAIL')
    else:
        return f'  ({i+1}) {value_str}'

def is_integer(value):
    try:
        int(value)
        return True
    except (ValueError, TypeError):
        return False

def prompt_choices(choices, default=None, label="value", unavailable_choices=None, hidden_models=None):
    value = None
    if unavailable_choices is None:
        unavailable_choices = []
        available_choices = choices
    else:
        available_choices = [c for c in choices if c not in unavailable_choices]

    wildcard = any("*" in choice for choice in available_choices)

    while (value not in (available_choices + (hidden_models or []))) or ("*" in value):
        if value:
            print(f"Invalid {label}: {value}")
        value = input(f"""Please choose a {label}:
{'\n'.join(map(partial(format_choice, default=default, unavailable=unavailable_choices),
               enumerate(available_choices + unavailable_choices)))}
(type number or any name or alias or press [Enter])...
""")
        if value == "":
            value = default or available_choices[0]

        if is_integer(value):
            try:
                value = available_choices[int(value) - 1]
            except IndexError:
                continue

        if "*" in value:
            continue

        # can match any other choice so we break
        if wildcard:
            break

    assert "*" not in value
    return value[0] if type(value) in [list, tuple] else value


def check_dependencies(backend, dependencies=None, raise_error=False):
    from importlib import import_module
    modules = dependencies or [backend]
    try:
        for module in modules:
            import_module(module)
        return True
    except ImportError:
        # if requested by the user, raise an Exception
        if raise_error:
            raise
        return False
    return False