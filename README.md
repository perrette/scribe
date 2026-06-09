[![pypi](https://img.shields.io/pypi/v/scribe-cli)](https://pypi.org/project/scribe-cli)
![](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fperrette%2Fscribe%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)
[![docs](https://img.shields.io/badge/docs-perrette.github.io%2Fscribe-blue)](https://perrette.github.io/scribe/)

# Scribe  <img src="https://github.com/perrette/scribe/raw/main/scribe_data/share/icon.png" width="48">

Scribe is a speech-to-text CLI and tray app that pipes transcribed text
into the focused window. It supports local and cloud-based APIs, batch and
streaming workflows.

<!-- intro-start -->
- **Five backends, one interface.** Records from your mic and transcribes via
  **Vosk** (local, streaming), **Whisper** (local, batch), **Whisper FUTO**
  (local, batch — ACFT-tuned for short dictations), **OpenAI** (cloud, batch
  *or* streaming), or **Groq** (cloud, batch).
- **Four ways to deliver the transcript.** Paste into the focused window
  (default), copy to the clipboard, print to the terminal, or append to a file.
- **Tray or terminal.** Runs as a **system tray icon** with a single Record
  button, or as an interactive **terminal TUI** — same menu in both.
- **Hotkey-friendly.** Hooks into your desktop's keyboard shortcuts via
  `SIGUSR1` (toggle recording) and `SIGUSR2` (cancel), plus built-in global
  hotkeys on X11 / Windows.
- **Cross-platform.** Tested on Ubuntu (X11 and Wayland), macOS, and Windows;
  works under Termux for clipboard / terminal output.
<!-- intro-end -->

<img src=https://raw.githubusercontent.com/perrette/scribe/main/docs/app-tray-menu.png width=300px>

## Installation

**Linux / macOS:**

```bash
sudo apt-get install portaudio19-dev xclip   # Ubuntu; macOS: brew install portaudio
pip install scribe-cli[all]
export GROQ_API_KEY=YOURAPIKEY                # or OPENAI_API_KEY, or skip and run local
```

**Windows** (PowerShell) — no system packages needed; `sounddevice` bundles
PortAudio and the clipboard is native, so skip the `apt`/`brew` step:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install scribe-cli[whisper]        # local Whisper; or [all], or a cloud backend
$env:GROQ_API_KEY = "YOURAPIKEY"        # or OPENAI_API_KEY, or skip and run local
```

See the [installation page](https://perrette.github.io/scribe/installation/)
for the full per-platform walkthrough (extras, Ubuntu / GNOME tray libs, the
Windows quickstart).

## Quickstart

```bash
scribe
```

This launches the system tray icon. Press Record, speak, press Stop — the
transcription lands in the focused window. Scribe picks the first backend whose
key / dependency is present, in order **`groq` → `openai` → `whisper-futo` →
`whisper` → `vosk`**. Override the defaults or drop the tray entirely:

```bash
scribe --backend whisper --model small   # local, no API key
scribe --frontend terminal               # interactive TUI menu
scribe --mode clipboard                  # copy to clipboard, no keystroke
```

See the [quickstart](https://perrette.github.io/scribe/quickstart/) for more.

## Documentation

Full documentation lives at **<https://perrette.github.io/scribe/>**:

- [Installation & dependencies](https://perrette.github.io/scribe/installation/)
  — PortAudio, extras, Ubuntu / GNOME tray libs, Windows.
- [Quickstart](https://perrette.github.io/scribe/quickstart/) — your first
  dictation.
- [Backends in detail](https://perrette.github.io/scribe/backends/) — model
  lists, streaming recipes, vocabulary biasing, the realtime model.
- [Output modes & typer backends](https://perrette.github.io/scribe/output/) —
  keystroke vs clipboard, Wayland / `eitype`, `--type-direct`.
- [System tray & global hotkeys](https://perrette.github.io/scribe/tray/) —
  menu tree, icon states, `SIGUSR1`/`SIGUSR2`.
- [Desktop entry & autostart (`scribe-install`)](https://perrette.github.io/scribe/desktop-install/)
  — GNOME / KDE launcher integration.
- [Fine tuning & CLI reference](https://perrette.github.io/scribe/cli/) — every
  `scribe --help` flag with examples.

## From the same author

A few related tools I maintain, useful in a Markdown-based scientific workflow.

**Scientific writing & data**

- [**texmark**](https://perrette.github.io/texmark/) — write scientific articles in Markdown and convert them to journal-ready LaTeX/PDF.
- [**papers**](https://perrette.github.io/papers/) — command-line BibTeX bibliography and PDF library manager.
- [**datamanifest**](https://perrette.github.io/datamanifest/) — declarative, reproducible dataset management. *(See also the [datamanifest.toml](https://perrette.github.io/datamanifest.toml/) format spec and the [DataManifest.jl](https://awi-esc.github.io/DataManifest.jl/) Julia port.)*

**Voice helpers** — handy for dictating and proofreading drafts by ear

- [**scribe**](https://perrette.github.io/scribe/) — speech-to-text dictation (Whisper).
- [**bard**](https://perrette.github.io/bard/) — text-to-speech reader (Kokoro / Piper).

## Compatibility

| OS                 | Status                                                              |
|--------------------|---------------------------------------------------------------------|
| Ubuntu 24.04       | Primary dev platform (GNOME, X11 and Wayland).                      |
| macOS              | Works.                                                              |
| Windows 11         | Tested and working on Python 3.14 (64-bit / `win_amd64`). Dependencies resolve pre-built wheels; no C toolchain or Python downgrade needed. |

Wayland keystroke injection is convoluted but
[solved](https://perrette.github.io/scribe/output/).
