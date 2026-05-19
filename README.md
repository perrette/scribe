[![pypi](https://img.shields.io/pypi/v/scribe-cli)](https://pypi.org/project/scribe-cli)
![](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fperrette%2Fscribe%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)

# Scribe  <img src="https://github.com/perrette/scribe/raw/main/scribe_data/share/icon.png" width="48">

**Talk. It types.** Scribe is a speech-to-text CLI and tray app that
pipes transcribed text straight into the focused window. It supports local and
cloud-based APIs, batch and streaming workflows.

## What it does

- Records from your mic and transcribes via one of four backends —
  **Vosk** (local, streaming), **Whisper** (local, batch), **OpenAI**
  (cloud, batch *or* streaming), **Groq** (cloud, batch).
- Delivers the transcript three ways: paste into the focused window
  (default), copy to clipboard, or print to the terminal.
- Runs as a **system tray icon** with a single Record button, or as an
  interactive **terminal TUI** — same menu in both.
- Hooks into your DE's keyboard shortcuts via `SIGUSR1` (toggle
  recording) and `SIGUSR2` (cancel).
- Cross-platform: tested on Ubuntu (X11 and Wayland), macOS, Windows;
  works under Termux for clipboard / terminal output.

## Getting started

```bash
sudo apt-get install portaudio19-dev xclip   # Ubuntu; macOS: brew install portaudio
pip install scribe-cli[all]
export GROQ_API_KEY=YOURAPIKEY                # or OPENAI_API_KEY, or skip and run local
scribe
```

Scribe picks the first backend whose key / dependency is present, in
order **`groq` → `openai` → `whisper` → `vosk`**, and launches the
tray icon. Press Record, speak, press Stop.

See documentation below for setting up keyboard input on Ubuntu Wayland.


## Backends at a glance

| Backend         | `--backend` | Default model              | Streaming model(s)        | Requires                            |
|-----------------|-------------|----------------------------|---------------------------|-------------------------------------|
| Groq (cloud)    | `groq`      | `whisper-large-v3-turbo`   | —                         | `GROQ_API_KEY`                      |
| OpenAI (cloud)  | `openai`    | `gpt-4o-mini-transcribe`   | `gpt-realtime-whisper`    | `OPENAI_API_KEY`                    |
| Whisper (local) | `whisper`   | `small`                    | —                         | `pip install scribe-cli[whisper]`   |
| Vosk (local)    | `vosk`      | language-dependent         | all Vosk models           | `pip install scribe-cli[vosk]`      |

Whether a transcription appears live as you speak or all at once when
you stop depends on the **model** picked — see
[docs/backends.md](docs/backends.md).

## Documentation

- [Installation & dependencies](docs/installation.md) — PortAudio,
  extras, Ubuntu / GNOME tray libs.
- [Backends in detail](docs/backends.md) — model lists, when to pick
  which, the realtime model.
- [Keyboard modes & typer backends](docs/keyboard.md) — keystroke vs
  clipboard, Wayland / `eitype`, `--type-direct`.
- [System tray & global hotkeys](docs/tray.md) — menu tree, icon
  states, `SIGUSR1`/`SIGUSR2`.
- [Desktop entry & autostart (`scribe-install`)](docs/desktop-install.md)
  — GNOME / KDE launcher integration.
- [Fine tuning & CLI reference](docs/cli.md) — every `scribe --help`
  flag with examples.

## Compatibility

Initially developed for Python 3 on Ubuntu 24.04 (GNOME + Wayland);
works on macOS and Windows too. Wayland keystroke injection is
convoluted but [solved](docs/keyboard.md). For dependencies of
individual subsystems, check `pynput` (keyboard) and `pystray` (tray
icon).
