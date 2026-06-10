# Installation & dependencies

Scribe is a Python package distributed on PyPI as
[`scribe-cli`](https://pypi.org/project/scribe-cli) (the `-cli` suffix
disambiguates it from an unrelated package). It runs on Linux (X11 and
Wayland), macOS, and Windows; on Android it works under Termux for
clipboard / terminal output.

## System dependencies

Scribe records audio via PortAudio (through `sounddevice`) and reads /
writes the clipboard via `xclip` on Linux — preferred over `wl-copy`
on Wayland, where the latter briefly steals keyboard focus on GNOME
< 47 and breaks pasting into Electron apps (see
[Clipboard backend on Wayland](output.md#clipboard-backend-on-wayland)).
On Ubuntu:

```bash
sudo apt-get install portaudio19-dev xclip
```

On macOS use Homebrew:

```bash
brew install portaudio
```

On Windows there are **no system packages to install**: `sounddevice`
bundles PortAudio in its wheel and the clipboard uses the native Windows
API, so neither `portaudio19-dev` nor `xclip` apply. See the
[Windows quickstart](#windows) below.

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
| `[keyboard]` | `pynput`                                           | back-compat only — `pynput` is a base dep now |
| `[app]`      | `PyGObject` (Linux only)                            | the Linux AppIndicator tray binding     |
| `[all]`      | every backend + Linux tray binding                 | one-shot setup                          |

> **`pynput` and `pystray` are base dependencies.** The default run uses
> the keyboard typer and the system-tray app, so both ship with the plain
> `pip install scribe-cli` — you do **not** need `[keyboard]` or `[app]`
> for the standard experience. `[app]` now only adds the Linux-only
> `PyGObject` AppIndicator binding (skipped automatically on Windows/macOS
> via a `sys_platform == 'linux'` marker, since it needs GTK and won't
> pip-install elsewhere).

You need at least one backend extra (or none if you only plan to use
cloud backends *and* already have the `openai` package). The `groq`
backend reuses the `openai` client, so `[openai]` covers both.

## Windows

Windows 11 is tested and working on Python 3.14 (64-bit). Every
dependency — `onnxruntime`, `faster-whisper`/`ctranslate2`,
`pystray`/`Pillow`, `pynput` — resolves a ready-made `win_amd64` wheel,
so there is no build toolchain to install and no need to downgrade
Python.

From PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
# If activation is blocked by the execution policy, run once:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e .[whisper]      # or [all], or a cloud backend like [openai]
scribe
```

That's the whole setup. There are **no system packages** to install
(`apt`/`portaudio19-dev`/`xclip` are Linux-only) and **nothing to create
by hand** — earlier builds needed a manual `C:\tmp` folder, which is no
longer the case.

- **Tray icon:** appears under the taskbar overflow arrow (`^`) by
  default; pin it via *Settings → Personalization → Taskbar → Other
  system tray icons*. A single click on the icon starts recording.
- **Microphone:** if recording fails, enable *Settings → Privacy &
  security → Microphone → "Let desktop apps access your microphone"*.

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
`ydotool`) are OS-level binaries — see [output.md](output.md) for
when you need them and how to install each.

## Model cache

Local backends (Vosk, Whisper) download their model files on first use
to `$XDG_CACHE_HOME/<backend>` (defaults to `$HOME/.cache/<backend>`).
Override with `--download-folder-vosk` / `--download-folder-whisper`.
