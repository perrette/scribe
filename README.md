[![pypi](https://img.shields.io/pypi/v/scribe-cli)](https://pypi.org/project/scribe-cli)
![](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fperrette%2Fscribe%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)

# Scribe  <img src="https://github.com/perrette/bard/raw/main/bard_data/share/icon.png" width=48px>

`scribe` is a speech recognition tool that provides real-time transcription using cutting-edge AI models, with the goal of serving as a virtual keyboard on a computer.

It features local, downloadable models with the `vosk` and `whisper` backends, as well as a client to open AI via `openaiapi` backend (API key required).

## Compatibility

The package is initially developped for python 3.12 with Ubuntu 24.04 with Gnome + Wayland, but it should work on other platforms as well (feedback welcome).
Basically check the pages of the dependencies for more info (i.e. pynput for the keyboard, pystray for the app).

- python 3.13:
    - at the time of writing, `openai-whisper` does not install.

- Ubuntu:
    - see caveats in the use of the keyboard under Wayland [keyboard section](#use-the-keyboard-with-wayland).
- MacOS:
    - tested on a Macbook Air M1 8Gb RAM, with python 3.12. It runs, but poorly, presumably because of the low memory: prefer the `openaiapi` backend for such machines
    - I expect better memory specs will have the local models run fine
- Windows:
    - not tested yet

## Installation

Install PortAudio library (required by `sounddevice`) and xclip library (required by `pyperclip`). E.g. on Ubuntu:

```bash
sudo apt-get install portaudio19-dev xclip
```

(`portaudio19-dev` becomes `portaudio ` with homebrew)

See additional requirements for the [icon tray](#system-tray-icon-experimental-) and [keyboard](#virtual-keyboard-experimental) options. The python dependencies should be dealt with automatically:

```bash
pip install scribe-cli[all]
```

(note the `-cli` suffix for client)

or for local development:

```bash
git clone https://github.com/perrette/scribe.git
cd scribe
pip install -e .[all]
```

You can leave the optional dependencies (leave out `[all]`) but must install at least one of `vosk` or `openai-whisper` or `openai` packages (see Usage below).

At the time of writing `openai-whisper` does not install on `python 3.13`. You can install the packages manually and skip that package. This makes the `whisper` API unavailable.

### Manual selection of the dependencies

```bash
# language models (at least one must be installed !)
pip install vosk
pip install openai soundfile  # openaiapi
pip install openai-whisper   # FAILS IN PYTHON 3.13 on Ubuntu

# PortAUDIO (sounddevice)
pip install sounddevice # automatically installed as required dependency
sudo apt-get install portaudio19-dev
# MAC OS: brew install portaudio

# clipboard
pip install pyperclip  # automatically installed as required dependency
sudo apt-get install xclip

# keyboard
pip install pynput

# app mode
sudo apt install libcairo-dev libgirepository1.0-dev gir1.2-appindicator3-0.1  # Ubuntu ONLY (not needed on MacOS)
pip install PyGObject # Ubuntu ONLY (not needed on MacOS)
pip install pystray

# And finally
pip install scribe-cli
```

The language models for local backends `vosk` and `whisper` will download on-the-fly.
The default download folder is `$XDG_CACHE_HOME/{backend}` where `$XDG_CACHE_HOME` defaults to `$HOME/.cache`.

## Usage

Just type in the terminal:

```bash
scribe
```
and the script will guide you through the choice of backend (`whisper` or `vosk` or `openaiapi`) and the specific language model.
After this, you will be prompted to start recording your microphone and print the transcribed text in real-time (`vosk`)
or until after recording is complete (`whisper`).
You can interrupt the recording via Ctrl + C and start again or change model.

The default (`whisper`) is excellent at transcribing a full-length audio sequences in [many languages](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages). It is really impressive,
but it cannot do real-time, and depending on the model can have relatively long execution time, especially with the `turbo` model (at least on my laptop with CPU only). The `small` model is also excellent and runs much faster. It is selected as default in `scribe` for that reason.
With the `whisper` model the registration stops after a 2-second silence is detected. You can also stop the registration manually before the transcription occurs (Ctrl + C or Stop in the `--app` mode).
By default, the recording will only last 120 seconds. You can fine-tune this behaviour via the `--silence`, `--duration` and `--restart-after-silence` parameters.

The `vosk` backend is much faster and very good at doing real-time transcription for one language, but tended to make more mistakes in my tests and it does not do punctuation.
It becomes really powerful when used for longer or interactive typing session with the [keyboard](#virtual-keyboard-experimental) option, e.g. to make notes or chat with an AI.
There are many [vosk models](https://alphacephei.com/vosk/models) available, and here a few are associated to [a handful of languages](scribe/models.toml) `en`, `fr`, `it`, `de` (so far).

The `openaiapi` backend uses `whisper-1` model at the time of writing. It requires an API key best passed as an environment variable, e.g. in bash:
```bash
export OPENAI_API_KEY=YOURAPIKEY
scribe --backend openaiapi
```
The `openaiapi` backend is lightweight and handy if you have an API (you can create one for free for testing) and a low-spec computer (and don't care too much about privacy, obviously).

## Output media

By default the transcription is printed on the terminal, but other output media are supported.

### Clipboard

The most straightforward is the clipboard:

```bash
scribe --clipboard
```
The content of the (full) transcription is then pasted to the clipboard, and it is up to the user to paste (e.g. Ctrl + V).

### Output file

Alternatively an output file can be indicated:

```bash
scribe -o transcription.txt
```

### Virtual keyboard (experimental)

With the `--keyboard` option `scribe` will attempt to simulate a keyboard and send transcribed characters to the application under focus:

```bash
scribe --keyboard
```

This can be extremely useful with the `vosk` backend and its realtime transcription, or alternatively with the `--restart` option with the `whisper` backend.

The `--keyboard` option relies on the optional `pynput` dependency (installed together with `scribe` if you used the `[all]` or `[keyboard]` option).
Depending on your operating system, `pynput` may require additional configuration to work around its [limitations](https://pynput.readthedocs.io/en/latest/limitations.html).

#### Use the keyboard with Wayland

In my Ubuntu 24.04 + Wayland system the keyboard simulation works out-of-the-box in chromium based applications (including vscode) but it does not in firefox and sublime text and any of the rest (not even in a terminal !). I am told this is because Chromium runs an X server emulator and so is compatible with the default pynput backend.

One workaround is to use the Xorg version of GNOME: in `etc/gdm3/custom.conf` uncomment `# WaylandEnable=false` and restart your computer.

Another workaround while staying with Wayland is to use the low-level `uinput` backend of `pynput`, but that requires that `scribe` is run as root (sudo), and likely other configurations like activating the `uinput` system module (`sudo modprobe uinput` for a one-time test, or adding `uinput` to `/etc/modules-load.d/modules.conf` to make that persistent).
Moreover, the keyboard must be set with an appropriate layout, for example to have the letter `é` you'd want a French or Italian layout otherwise the English will drop it or replace with something else. Another caveat I encountered is that the special characters (`é`) were inserted at the wrong place. Adding a small delay was enough to fix that with the additional parameter `--latency 0.01` Finally if you run as sudo you may need to reset some environment variable so that the list of audio devices (`XDG_RUNTIME_DIR`) and the download folder remain the same. To sum-up, that gives something like:
```bash
sudo modprobe uinput
sudo HOME=$HOME XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR PYNPUT_BACKEND_KEYBOARD=uinput $(which scribe)  --latency 0.01
```
You're on the right path :)

## System tray icon (experimental) <img src="https://github.com/perrette/bard/raw/main/bard_data/share/icon.png" width=48px>

<img src=https://github.com/user-attachments/assets/4c97f4b1-1a65-4d49-9f5a-a9f4287cfa5a width=300px>

To avoid switching back and forth with the terminal, it's possible to interact with the program via an icon tray.
To activate start with:
```bash
scribe --app ...
```
or toggle the app option in the interactive menu. The scribe icon will show, with Record and other options. The icon will change based on what the app is doing. It is possible to choose from a set
of predefined models (controlled by `--vosk-models` and `whisper-models`) and options, or to Quit and choose from the terminal before pressing Enter again.
For the vosk model, there are only two states : recording + transcribing or Idle. For the whisper model there are three states visible from the icon: recording/waiting, transcribing and idle.
That option requires `pystray` to be installed. This is included with the `pip install ...[all]` option.

The `--vosk-models` and `--whisper-models` allow to predefined the set of available models to choose from in the app manu. E.g.
```bash
scribe --app --vosk-models vosk-model-fr-0.22 --whisper-models small turbo ...
```

### Ubuntu

In Ubuntu the following dependencies were required to make the menus appear:

```bash
sudo apt install libcairo-dev libgirepository1.0-dev gir1.2-appindicator3-0.1
pip install PyGObject
```

## Start as an application in GNOME

If you run Ubuntu (or else?) with GNOME, the script `scribe-install [...]` will create a `scribe.desktop` file and place it under `$HOME/.local/share/applications`
to make it available from the quick launch menu. Any option will be passed on to `scribe`, with the additional options `--name` and `--no-terminal`.
`--no-terminal` means no terminal will show up, and it also implies the options `--app --no-prompt`.

Consider the following two flavors:
```bash
scribe-install --clipboard ...
scribe-install --name "Scribe App" --no-terminal --clipboard ...
```
The first will create an app named Scribe (the default) that simply opens a terminal and execute the command `scribe --clipboard ...`.
The second will create an app named Scribe App that executes in a hidden terminal: `scribe --no-prompt --app --clipboard ...`, thus leaving the tray icon as only mode of interaction.


## Fine tuning

There are a number of options to control the silence threshold, duration and more.
Best is to check the available options in the online help:

```bash
scribe --help
```
