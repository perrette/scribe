# System tray & global hotkeys

<img src="https://github.com/perrette/scribe/raw/main/scribe_data/share/icon.png" width="48">

<img src="https://raw.githubusercontent.com/perrette/scribe/main/docs/app-tray-menu.png" width="300">

Tray mode is the default — running `scribe` with no arguments launches
the system tray icon. If you'd rather use the interactive terminal
menu, pass `--frontend terminal`:

```bash
scribe                       # tray (default)
scribe --frontend terminal   # interactive TUI
```

From inside the TUI menu you can toggle to tray mode at any time. The
scribe icon shows Record, Cancel (discards an in-flight recording
without transcribing), and other options. The icon changes based on
what the app is doing.

For **streaming models** (Vosk; OpenAI `gpt-realtime-whisper`) the
icon has two states: recording-and-transcribing or idle. For **batch
models** (Whisper, OpenAI `gpt-4o-*`, Groq) the icon has three states:
recording / waiting, transcribing, and idle.

Transcription and API errors are surfaced as a pop-up dialog instead
of just crashing the tray.

The tray requires `pystray` (and on Linux, `PyGObject` plus the
appindicator system libs — see [installation.md](installation.md)).
This is included with `pip install scribe-cli[all]` or `[app]`.

You can predefine which models appear in the tray menu with
`--vosk-models` and `--whisper-models`:

```bash
scribe --vosk-models vosk-model-fr-0.22 \
       --whisper-models small large-v3-turbo
```

## Menu structure

Both the tray and terminal frontends share the same menu tree:

```
Record                          start recording (default tray action)
Stop / Cancel                   end or discard an in-flight recording
Mode: Stream / Clip             toggle live-chunk transcription on batch
                                  backends (whisper, whisper-futo,
                                  openai gpt-4o-*, groq). Reads as
                                  "Mode: Stream (native)" on native
                                  streamers (vosk, gpt-realtime-whisper),
                                  where clicking is a no-op.
Model ▶                         per-vendor submenus, ordered:
    Whisper (local) ▶             models via --whisper-models — 'small (recommended)'
    Vosk (local, streaming) ▶     models via --vosk-models
    OpenAI ▶                      gpt-4o-transcribe, gpt-4o-mini-transcribe,
                                    gpt-realtime-whisper (streaming)
    Groq ▶                        whisper-large-v3-turbo
Options ▶
    Stream (advanced) ▶           visible iff Mode=Stream
        Chunk min: 1.5s             batch backends only; minimum buffer before
                                    a silence-cut is allowed
        Chunk max: 10s              batch backends only; force-cut threshold
        Silence break: 0.6s         batch backends only; special values:
                                    Auto (longest silence in window),
                                    Max (force-cut only, no silence trigger)
        Context reset: 3× silence   batch backends only; greyed when silence-
          (= 1.8s)                  break is Auto or Max
        Realtime timeout: Always On always visible when Mode=Stream
        Stream: Live / Offline      visible iff gpt-realtime-whisper; unifies
          after Xs                  --realtime-gate and --realtime-commit-silence
    Clip timeout: 2 min           visible iff Mode=Clip
    Keyboard mode ▶               Clipboard only / Send to focused window /
                                    Terminal only   (mirrors --mode)
    Toggle tray app mode          (terminal frontend only)
    Keyboard backend ▶            eitype / pynput / ydotool / wtype
                                  (rows incompatible with this OS are hidden;
                                   submenu hidden entirely when ≤ 1 row left)
    Advanced ▶                    VAD mode toggle (silero ↔ dB), per-mode
                                    VAD knobs (silero: speech-probability
                                    threshold, min silence duration; dB:
                                    silence threshold — only the active
                                    mode's knobs are shown)
Quit
```

Vendor submenus only appear for backends whose dependency / API key is
present; missing ones are listed at the bottom of the Model menu in a
disabled "<vendor> — <reason>" row so you know what's missing.

## Global hotkey integration

In tray / app mode scribe writes its PID to a pidfile and listens for
two signals:

- `SIGUSR1` — toggle recording (same as clicking Record / Stop).
- `SIGUSR2` — cancel an in-flight recording.

Bind these to keyboard shortcuts in your desktop environment to start
/ stop / cancel scribe from anywhere. The pidfile lives at
`$XDG_RUNTIME_DIR/scribe.pid` (`/tmp/scribe.pid` if unset):

```bash
kill -SIGUSR1 $(cat "${XDG_RUNTIME_DIR:-/tmp}/scribe.pid")  # toggle record
kill -SIGUSR2 $(cat "${XDG_RUNTIME_DIR:-/tmp}/scribe.pid")  # cancel
```

This is the recommended way to drive scribe from a keyboard shortcut
(GNOME Settings → Keyboard → Custom Shortcuts, KDE's hotkey daemon,
sxhkd, etc.) without the typer-backend complications of trying to
intercept keys directly.
