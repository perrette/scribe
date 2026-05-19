[![pypi](https://img.shields.io/pypi/v/scribe-cli)](https://pypi.org/project/scribe-cli)
![](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fperrette%2Fscribe%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)

# Scribe  <img src="https://github.com/perrette/bard/raw/main/bard_data/share/icon.png" width=48px>

`scribe` is a speech recognition tool that provides real-time transcription using cutting-edge AI models, with the goal of serving as a virtual keyboard on a computer.

## Backends

It supports four backends; Groq is the default cloud backend when `GROQ_API_KEY` is set:

| Backend | Display label | `--backend` | Type | Default model | Requires |
|---------|--------------|-------------|------|---------------|---------|
| Groq | `Groq` | `groq` | cloud | `whisper-large-v3-turbo` | `GROQ_API_KEY` |
| OpenAI | `OpenAI` | `openai` | cloud | `gpt-4o-mini-transcribe` | `OPENAI_API_KEY` |
| Whisper | `Whisper (local)` | `whisper` | local | `large-v3-turbo` | `pip install scribe-cli[whisper]` |
| Vosk | `Vosk (local, live partials)` | `vosk` | local | language model | `pip install scribe-cli[vosk]` |

When started without `--backend`, scribe picks the first available backend in order: `groq` → `openai` → `whisper` → `vosk`.

> **Naming note.** `openai` is the cloud OpenAI backend (model: `gpt-4o-mini-transcribe`); `whisper` is the *local* [faster-whisper](https://github.com/SYSTRAN/faster-whisper) backend — a different model pipeline from OpenAI's `whisper-1` (deprecated) and Groq's `whisper-large-v3-turbo`. The tray and terminal menus show vendor-prefixed labels (`OpenAI`, `Groq`, `Whisper (local)`, `Vosk (local, live partials)`) to make this unambiguous.
>
> **Migration note.** The OpenAI cloud backend is now selected with `--backend openai`. The `whisper-1` model is still selectable via `Choose Model → OpenAI` but is deprecated in favour of `gpt-4o-mini-transcribe`.

## Compatibility

The package is initially developped for python 3.12 with Ubuntu 24.04 with Gnome + Wayland, but it should work on other platforms as well (feedback welcome).
Basically check the pages of the dependencies for more info (i.e. pynput for the keyboard, pystray for the app).

- Ubuntu:
    - see caveats in the use of the keyboard under Wayland [keyboard section](#use-the-keyboard-with-wayland).
- MacOS:
    - tested on a Macbook Air M1 8Gb RAM, with python 3.12. It runs, but poorly, presumably because of the low memory: prefer a remote backend (`groq` or `openai`) for such machines
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

You can leave the optional dependencies (leave out `[all]`) but must install at least one of `vosk` or `faster-whisper` or `openai` packages (see Usage below). The `groq` backend reuses the `openai` client, so installing the `openai` extra is enough for both `openai` and `groq`.

### Manual selection of the dependencies

```bash
# language models (at least one must be installed !)
pip install vosk
pip install openai soundfile  # openai and groq
pip install faster-whisper

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
and the script will guide you through the choice of backend (`groq`, `openai`, `whisper` or `vosk`) and the specific language model. The first backend whose dependency or API key is present is selected by default, with a preference for the cloud ones.
After this, you will be prompted to start recording your microphone and print the transcribed text in real-time (`vosk`)
or until after recording is complete (`whisper`, `openai`, `groq`).
You can interrupt the recording via Ctrl + C and start again or change model.

### `whisper` (local)

The `whisper` backend runs locally via [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) and defaults to the `large-v3-turbo` model. It is excellent at transcribing full-length audio sequences in [many languages](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages), but it cannot do real-time and the execution time depends on the model and hardware. Smaller models (`small`, `medium`) trade accuracy for speed.

With the `whisper`, `openai`, and `groq` backends the recording continues for 2 minutes until you stop it manually to trigger the transcription (Stop in the app, Ctrl + C in the terminal).
These parameters can be changed. There is also the possibility to interrupt after a silence is detected. For example `--silence-db -40 --silence 2` interrupts recording when a silence (less than -40 dB recorded) lasts more than 2 seconds. The default `--silence-db -200` / `--silence 120` effectively disables this feature and keeps full manual control.

### `vosk` (local, streaming)

The `vosk` backend is much faster and very good at real-time transcription for one language, but tends to make more mistakes than whisper and it does not produce punctuation.
It becomes really powerful in longer or interactive typing sessions with the [keyboard](#virtual-keyboard-experimental) option, e.g. to make notes or chat with an AI.
There are many [vosk models](https://alphacephei.com/vosk/models) available, and a handful are associated to [common languages](scribe/models.toml) `en`, `fr`, `it`, `de` (so far).

### `openai` (OpenAI cloud)

The `openai` backend defaults to `gpt-4o-mini-transcribe` (`whisper-1` is also selectable but deprecated). It requires an API key best passed as an environment variable:
```bash
export OPENAI_API_KEY=YOURAPIKEY
scribe --backend openai
```
Lightweight and handy if you have an API key and a low-spec computer (and don't care too much about privacy, obviously).

### `groq` (Groq cloud)

The `groq` backend talks to Groq's OpenAI-compatible API and uses `whisper-large-v3-turbo`. It is typically the fastest option for full-utterance transcription:
```bash
export GROQ_API_KEY=YOURAPIKEY
scribe --backend groq
```

## Output media

By default the transcription is printed on the terminal, but other output media are supported.

### Clipboard

The most straightforward is the clipboard:

```bash
scribe --clipboard
```
The content of the (full) transcription is then placed on the clipboard, and it is up to the user to paste (e.g. Ctrl + V).

Add `-p` / `--auto-paste` to have scribe synthesize the paste keystroke
itself once the transcription lands on the clipboard:

```bash
scribe --clipboard --auto-paste
```

This is convenient when scribe runs in the background (tray / app mode)
and you want the transcribed text to land directly in the focused window.
Ignored if `--keyboard` is also set.

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

This can be extremely useful with the `vosk` backend and its realtime transcription, or alternatively with the `--restart-after-silence` (`-a`) option with the `whisper` backend.

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

Tray mode is the default — running `scribe` with no arguments launches the system tray icon. If you'd rather use the interactive terminal menu, pass `--frontend terminal`:
```bash
scribe                       # tray (default)
scribe --frontend terminal   # interactive TUI
```
From inside the TUI menu you can toggle to tray mode at any time. The scribe icon will show, with Record, Cancel (discards an in-flight recording without transcribing) and other options. The icon changes based on what the app is doing. It is possible to choose from a set
of predefined models (controlled by `--vosk-models` and `--whisper-models`) and options, or to Quit and choose from the terminal before pressing Enter again.
For the vosk model, there are only two states : recording + transcribing or Idle. For the whisper / openai / groq backends there are three states visible from the icon: recording/waiting, transcribing and idle.

Transcription and API errors are surfaced as a pop-up dialog instead of just
crashing the tray.

That option requires `pystray` to be installed. This is included with the `pip install ...[all]` option.

The `--vosk-models` and `--whisper-models` allow to predefine the set of available models to choose from in the app menu. E.g.
```bash
scribe --vosk-models vosk-model-fr-0.22 --whisper-models small turbo ...
```

#### Menu structure

Both the tray and terminal frontends share the same menu tree:

```
Record                        start recording (default tray action)
Stop / Cancel                 end or discard an in-flight recording
Choose Model ▶                per-vendor submenus:
    OpenAI ▶                    gpt-4o-mini-transcribe, whisper-1 (deprecated)
    Groq ▶                      whisper-large-v3-turbo
    Whisper (local) ▶           models via --whisper-models (default: large-v3-turbo)
    Vosk (local) ▶              models via --vosk-models
Toggle Options ▶              clipboard, keyboard, auto-paste, latency, …
Quit
```

#### Global hotkey integration

In tray / app mode scribe writes its PID to a pidfile and listens for two
signals:

- `SIGUSR1` — toggle recording (same as clicking Record / Stop).
- `SIGUSR2` — cancel an in-flight recording.

Bind these to keyboard shortcuts in your desktop environment to start /
stop / cancel scribe from anywhere. The pidfile lives at
`$XDG_RUNTIME_DIR/scribe.pid` (`/tmp/scribe.pid` if unset):

```bash
kill -SIGUSR1 $(cat "${XDG_RUNTIME_DIR:-/tmp}/scribe.pid")  # toggle record
kill -SIGUSR2 $(cat "${XDG_RUNTIME_DIR:-/tmp}/scribe.pid")  # cancel
```

### Ubuntu

In Ubuntu the following dependencies were required to make the menus appear:

```bash
sudo apt install libcairo-dev libgirepository1.0-dev gir1.2-appindicator3-0.1
pip install PyGObject
```

## Start as an application in GNOME

If you run Ubuntu (or else?) with GNOME, the script `scribe-install [...]` will create a `scribe.desktop` file and place it under `$HOME/.local/share/applications`
to make it available from the quick launch menu. Any option will be passed on to `scribe`, with the additional options `--name` and `--frontend {tray,terminal}` (default: `tray`).

Consider the following two flavors:
```bash
scribe-install --name "Scribe" --clipboard ...
scribe-install --name "Scribe Terminal" --frontend terminal --clipboard ...
```
The first (default) creates an app named Scribe that runs in tray mode (no terminal window), with the tray icon as the only mode of interaction.
The second creates an app named Scribe Terminal that opens a terminal window and runs the interactive TUI.


## Fine tuning

There are a number of options to control the silence threshold, duration and more.
Best is to check the available options in the online help:

```bash
scribe --help
```
