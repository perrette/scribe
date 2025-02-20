[![python](https://img.shields.io/badge/python-3.12-blue.svg)]()
[![pypi](https://img.shields.io/pypi/v/scribe-cli)](https://pypi.org/project/scribe-cli)

# Scribe  <img src="scribe_data/share/icon.png" width=48px>

`scribe` is a local speech recognition tool that provides real-time transcription using vosk and whisper AI, with the goal of serving as a virtual keyboard on a computer.

## Compatibility

In principle `scribe` is compatible with any OS but I develop it under Ubuntu (Wayland) for my own purposes so glitches are likely on other configurations.
Moreover there are quite a bit of dependencies that rely on very OS-specific protocols under the hood, like access to the microphone, keyboard and clipboard,
and even though the python dependencies `scribe` relies on are not restricted to a single platform, there may be limitation and additional binaries to install.
This guide is based on python3.12 running on Ubuntu 24.04 with Gnome + Wayland, which is a relatively standard setting at the time of writing.
Note as of February 19, 2025 python 13 does not seem to produce any transcription (I am not sure which dependency is to blame).
A test on Mac OS (M1 Air with 8Gb RAM) worked with python 12, though with a much inferior performance compared to my own system (Lenovo T14 Gen 5 with i5 125U 32 Gb RAM).

## Installation

Install PortAudio library and xclip library. E.g. on Ubuntu:

```bash
sudo apt-get install portaudio19-dev xclip
```

See additional requirements for the [icon tray](#system-tray-icon-experimental) and [keyboard](#virtual-keyboard-experimental) options. The python dependencies should be dealt with automatically:

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

You can leave the optional dependencies (leave out `[all]`) but must install at least one of `vosk` or `openai-whisper` packages (see Usage below).

The `vosk` language models will download on-the-fly.
The default download folder is `$XDG_CACHE_HOME/{backend}` where `$XDG_CACHE_HOME` defaults to `$HOME/.cache` (note for the `whisker` backend
the default is left to the `openai-whisper` package and might change in the future).


## Usage

Just type in the terminal:

```bash
scribe
```
and the script will guide you through the choice of backend (`whisper` or `vosk`) and the specific language model.
After this, you will be prompted to start recording your microphone and print the transcribed text in real-time (`vosk`)
or until after recording is complete (`whisper`).
You can interrupt the recording via Ctrl + C and start again or change model. The full content of the transcription will be pasted to the clipboard by default, until interruption.

The default (`whisper`) is excellent at transcribing a full-length audio sequences in [many languages](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages). It is really impressive,
but it cannot do real-time, and depending on the model can have relatively long execution time, especially with the `turbo` model (at least on my laptop with CPU only). The `small` model is also excellent and runs much faster. It is selected as default in `scribe` for that reason.
With the `whisker` model you need to stop the registration manually before the transcription occurs (Ctrl + C), though
there is a maximum duration after which it will stop by itself, which is setup to 60s by default (unless `--duration` is set to something else).

The `vosk` backend is much faster and very good at doing real-time transcription for one language, but tended to make more mistakes in my tests and it does not do punctuation.
It becomes really powerful when used for longer or interactive typing session with the [keyboard](#virtual-keyboard-experimental) option, e.g. to make notes or chat with an AI.
There are many [vosk models](https://alphacephei.com/vosk/models) available, and here a few are associated to [a handful of languages](scribe/models.toml) `en`, `fr`, `it`, `de` (so far).

To skip the initial selection menu you can do:
```bash
scribe --backend whisper --model small --no-prompt
```
where `--no-prompt` jumps right to the recording (after the first interruption, you can still choose to change the backend and model).

### Virtual keyboard (experimental)

By default the content of the transcription is pasted to the clipboard, and it is up to the user to paste (e.g. Ctrl + V).
However with the `vosk` backend and its realtime transcription, it is very handy to have the keys sent directly to the keyboard.
That can be achieve with the `--keyboard` option.

With the `--keyboard` option `scribe` will attempt to simulate a keyboard and send transcribed characters to the applcation under focus:

```bash
scribe --keyboard
```

It relies on the optional `pynput` dependency (installed together with `scribe` if you used the `[all]` or `[keyboard]` option).
Depending on your operating system, `pynput` may require additional configuration to work around its [limitations](https://pynput.readthedocs.io/en/latest/limitations.html).

#### Use the keyboard in Ubuntu

In my Ubuntu + Wayland system the keyboard simulation works out-of-the-box in chromium based applications (including vscode) but it does not in firefox and sublime text and any of the rest (not even in a terminal !). I am told this is because Chromium runs an X server emulator and so is compatible with the default pynput backend.

One workaround is to use the Xorg version of GNOME: in `etc/gdm3/custom.conf` uncomment `# WaylandEnable=false` and restart your computer.

Another workaround while staying with Wayland is to use the low-level `uinput` backend of `pynput`, but that requires that `scribe` is run as root (sudo), and likely other configurations like activating the `uinput` system module (`sudo modprobe uinput` for a one-time test, or adding `uinput` to `/etc/modules-load.d/modules.conf` to make that persistent).
Moreover, the keyboard must be set with an appropriate layout, for example to have the letter `é` you'd want a French or Italian layout otherwise the English will drop it or replace with something else. Another caveat I encountered is that the special characters (`é`) were inserted at the wrong place. Adding a small delay was enough to fix that with the additional parameter `--latency 0.01` Finally if you run as sudo you may need to reset some environment variable so that the list of audio devices (`XDG_RUNTIME_DIR`) and the download folder remain the same. To sum-up, that gives something like:
```bash
sudo modprobe uinput
sudo HOME=$HOME XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR PYNPUT_BACKEND_KEYBOARD=uinput $(which scribe)  --latency 0.01
```
You're on the right path :)

### System tray icon (experimental) <img src="scribe_data/share/icon.png" width=48px>

To avoid switching back and forth with the terminal, it's possible to interact with the program via an icon tray.
To activate start with:
```bash
scribe --app
```
or toggle the app option in the interactive menu. The scribe icon will show, with Record or Quit options.
That option requires `pystray` to be installed. This is included with the `pip install ...[all]` option. In Ubuntu the following dependencies were required to make the menus appear:

```bash
sudo apt install libcairo-dev libgirepository1.0-dev gir1.2-appindicator3-0.1
pip install PyGObject
```

### Start as an application in Ubuntu

If you run Ubuntu (or else?) with GNOME, the script `scribe-install [...]` will create a `scribe.desktop` file and place it under `$HOME/.local/share/applications`
to make it available from the quick launch menu. Any option will be passed on to `scribe`.

e.g.

```bash
scribe-install --backend whisper --model small
```

After that just typing Cmd + scri... at any time from any where will conveniently start the app in its own terminal with the prescribed options.
