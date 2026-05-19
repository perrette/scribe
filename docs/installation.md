# Installation & dependencies

Scribe is a Python package distributed on PyPI as
[`scribe-cli`](https://pypi.org/project/scribe-cli) (the `-cli` suffix
disambiguates it from an unrelated package). It runs on Linux (X11 and
Wayland), macOS, and Windows; on Android it works under Termux for
clipboard / terminal output.

## System dependencies

Scribe records audio via PortAudio (through `sounddevice`) and reads /
writes the clipboard via `xclip` on Linux. On Ubuntu:

```bash
sudo apt-get install portaudio19-dev xclip
```

On macOS use Homebrew:

```bash
brew install portaudio
```

(Windows ships everything needed via the wheels.)

## Python package

The simplest install pulls every optional dependency:

```bash
pip install scribe-cli[all]
```

For local development from a clone:

```bash
git clone https://github.com/perrette/scribe.git
cd scribe
pip install -e .[all]
```

## Pick-and-choose extras

If you don't want everything, `scribe-cli` ships granular extras matching
the four backends and the tray UI:

| Extra        | Pulls in                                           | Needed for                              |
|--------------|----------------------------------------------------|-----------------------------------------|
| `[whisper]`  | `faster-whisper`                                   | local Whisper backend                   |
| `[vosk]`     | `vosk`                                             | local Vosk backend (streaming)          |
| `[openai]`   | `openai`, `soundfile`                              | OpenAI cloud backend (incl. realtime)   |
| `[groq]`     | `openai`, `soundfile`                              | Groq cloud backend                      |
| `[keyboard]` | `pynput`                                           | the `pynput` typer (XTest/Quartz/WinAPI)|
| `[app]`      | `pystray`, `PyGObject`                             | system tray icon                        |
| `[all]`      | all of the above                                   | one-shot setup                          |

You need at least one backend extra (or none if you only plan to use
cloud backends *and* already have the `openai` package). The `groq`
backend reuses the `openai` client, so `[openai]` covers both.

## Ubuntu / GNOME tray dependencies

The tray icon needs system libraries for the AppIndicator stack:

```bash
sudo apt install libcairo-dev libgirepository1.0-dev gir1.2-appindicator3-0.1
pip install PyGObject pystray
```

These come for free with `[all]` or `[app]`, but the apt packages must
be installed first so `PyGObject` can compile.

## Keyboard injection backends

The Python `pynput` package is the default typer and is pulled in by
`[keyboard]` / `[all]`. The other typer backends (`eitype`, `wtype`,
`ydotool`) are OS-level binaries — see [keyboard.md](keyboard.md) for
when you need them and how to install each.

## Model cache

Local backends (Vosk, Whisper) download their model files on first use
to `$XDG_CACHE_HOME/<backend>` (defaults to `$HOME/.cache/<backend>`).
Override with `--download-folder-vosk` / `--download-folder-whisper`.
