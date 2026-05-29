[![pypi](https://img.shields.io/pypi/v/scribe-cli)](https://pypi.org/project/scribe-cli)
![](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fperrette%2Fscribe%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)

# Scribe  <img src="https://github.com/perrette/scribe/raw/main/scribe_data/share/icon.png" width="48">

**Talk. It types.** Scribe is a speech-to-text CLI and tray app that
pipes transcribed text straight into the focused window. It supports local and
cloud-based APIs, batch and streaming workflows.

## What it does

- Records from your mic and transcribes via one of five backends —
  **Vosk** (local, streaming), **Whisper** (local, batch),
  **Whisper FUTO** (local, batch — ACFT-tuned for short dictations),
  **OpenAI** (cloud, batch *or* streaming), **Groq** (cloud, batch).
- Delivers the transcript four ways: paste into the focused window
  (default), copy to clipboard, print to the terminal, or write to
  a file.
- Runs as a **system tray icon** with a single Record button, or as an
  interactive **terminal TUI** — same menu in both.
- Hooks into your DE's keyboard shortcuts via `SIGUSR1` (toggle
  recording) and `SIGUSR2` (cancel).
- Cross-platform: tested on Ubuntu (X11 and Wayland), macOS, Windows;
  works under Termux for clipboard / terminal output.

## Install

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

The tray app and keyboard typing work out of the box on Windows — `pynput`
and `pystray` are regular dependencies, and there is nothing to create by
hand (no `C:\tmp`). See [docs/installation.md](docs/installation.md#windows)
for the full Windows walkthrough, and the documentation below for setting up
keyboard input on Ubuntu Wayland.


## Usage

In a terminal:

```bash
scribe
```

This launches the system tray icon. Press Record, speak, press Stop —
the transcription lands in the focused window. Scribe picks the first
backend whose key / dependency is present, in order **`groq` →
`openai` → `whisper-futo` → `whisper` → `vosk`**, so with `GROQ_API_KEY`
set the command above is equivalent to:

```bash
scribe --backend groq --model whisper-large-v3-turbo
```

<img src=https://raw.githubusercontent.com/perrette/scribe/main/docs/app-tray-menu.png width=300px>

You can override the defaults or drop the tray entirely:

```bash
scribe --backend openai --model gpt-4o-mini-transcribe # OpenAI sweet spot
scribe --backend openai --model gpt-realtime-whisper   # OpenAI streaming
scribe --backend whisper --model small                 # local, no API key
scribe --frontend terminal                             # interactive TUI menu
scribe --record                                        # start recording immediately on launch (works in tray or terminal)
scribe --record --frontend terminal --mode file        # one-shot batched dictation → file
scribe --record --frontend terminal --mode file --stream  # streamed: chunks appended live as you speak
scribe --mode clipboard                                # copy to clipboard, no keystroke
scribe --mode terminal                                 # only print to stdout
scribe --mode file -o transcript.txt                   # append to a file (no keystroke / clipboard)
```

With `--no-interactive` (terminal frontend only), scribe skips the
interactive menu and starts recording right away — handy for scripted,
one-shot transcriptions.

Bias the recogniser toward names, jargon, or a domain glossary with
`--prompt "free text hint"` and `--words word1 word2 ...` (each also
accepts a `--prompt-file` / `--words-file` companion). See
[docs/backends.md › Vocabulary biasing](docs/backends.md#vocabulary-biasing)
for what each backend does with them.


## Backends at a glance

| Backend              | `--backend`     | Default model              | Streaming model(s)        | Requires                               |
|----------------------|-----------------|----------------------------|---------------------------|----------------------------------------|
| Groq (cloud)         | `groq`          | `whisper-large-v3-turbo`   | —                         | `GROQ_API_KEY`                         |
| OpenAI (cloud)       | `openai`        | `gpt-4o-mini-transcribe`   | `gpt-realtime-whisper`    | `OPENAI_API_KEY`                       |
| Whisper FUTO (local) | `whisper-futo`  | `small`                    | —                         | `pip install scribe-cli[whisper-futo]` |
| Whisper (local)      | `whisper`       | `small`                    | —                         | `pip install scribe-cli[whisper]`      |
| Vosk (local)         | `vosk`          | language-dependent         | all Vosk models           | `pip install scribe-cli[vosk]`         |

Whether a transcription appears live as you speak or all at once when
you stop depends on the **model** picked — see
[docs/backends.md](docs/backends.md).


### Getting an API key

Groq is the **recommended cloud backend by default** — extremely fast
(by a wide margin compared to other cloud STT options, especially in
**Stream** mode where the per-chunk roundtrip latency dominates the
perceived speed), quite accurate, and the **free tier** is generous
enough for everyday dictation. Sign up at
[console.groq.com](https://console.groq.com/), create an API key
under **Settings → API Keys**, and export it as `GROQ_API_KEY`.

I personally use [OpenAI](https://openai.com/api/) with `gpt-4o-mini-transcribe` as it is also fast and perhaps more accurate for my accent-tainted English.


## Documentation

- [Installation & dependencies](docs/installation.md) — PortAudio,
  extras, Ubuntu / GNOME tray libs.
- [Backends in detail](docs/backends.md) — model lists, when to pick
  which, the realtime model, [Streaming recipes](docs/backends.md#streaming-recipes--two-profiles)
  (Balanced / Patient profiles).
- [Output modes & typer backends](docs/output.md) — keystroke vs
  clipboard, Wayland / `eitype`, `--type-direct`.
- [System tray & global hotkeys](docs/tray.md) — menu tree, icon
  states, `SIGUSR1`/`SIGUSR2`.
- [Desktop entry & autostart (`scribe-install`)](docs/desktop-install.md)
  — GNOME / KDE launcher integration.
- [Fine tuning & CLI reference](docs/cli.md) — every `scribe --help`
  flag with examples.

## Related projects

- **[bard](https://github.com/perrette/bard)** — TTS sibling of scribe,
  same tray/CLI architecture in reverse: highlight text, hear it
  spoken. Shares the [`desktop-ai-core`](https://github.com/perrette/desktop-ai-core)
  backbone (frontends, providers, dialog helpers).

## Compatibility

| OS                 | Status                                                              |
|--------------------|---------------------------------------------------------------------|
| Ubuntu 24.04       | Primary dev platform (GNOME, X11 and Wayland).                      |
| macOS              | Works.                                                              |
| Windows 11         | Tested and working on Python 3.14 (64-bit / `win_amd64`). Every dependency resolves a ready-made wheel — no toolchain or Python downgrade needed. |

Wayland keystroke injection is convoluted but [solved](docs/output.md).
For dependencies of individual subsystems, check `pynput` (keyboard) and
`pystray` (tray icon).

**Windows notes:**

- The tray icon is hidden under the taskbar overflow arrow (`^`) by
  default. Pin it via *Settings → Personalization → Taskbar → Other
  system tray icons*.
- A **single click** on the tray icon fires the default action (Record).
  This is a free bonus of pystray's Win32 backend; on Ubuntu the
  AppIndicator backend only opens the menu (a backend limitation, not a
  bug).
- If recording fails, allow mic access under *Settings → Privacy &
  security → Microphone → "Let desktop apps access your microphone"*.
