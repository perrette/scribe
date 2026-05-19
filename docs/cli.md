# Fine tuning & CLI reference

For a complete, always-current listing run:

```bash
scribe --help
```

The flags are grouped to mirror the source-of-truth in
[`scribe/app.py`](../scribe/app.py).

## Backend

| Flag                            | Purpose                                                                 |
|---------------------------------|-------------------------------------------------------------------------|
| `--backend {vosk,whisper,openai,groq}` | Speech-recognition backend (prompted if omitted).                |
| `--model NAME`                  | Model name for the chosen backend. Auto-routes to the right backend for known model names (e.g. `--model gpt-realtime-whisper` selects `openai`). |
| `-l, --language LANG`           | Language alias selecting a preset Vosk model (`en`/`fr`/`de`/`it`), or `en` for English-only Whisper models. |
| `--api-key KEY`                 | API key for cloud backends; falls back to `OPENAI_API_KEY` / `GROQ_API_KEY` env. |
| `--download-folder-whisper DIR` | Folder to store Whisper models.                                         |
| `--download-folder-vosk DIR`    | Folder to store Vosk models.                                            |

## Audio

| Flag                  | Purpose                                                  |
|-----------------------|----------------------------------------------------------|
| `--input-device N`    | Microphone device index (see `python -m sounddevice`).   |

## Output

| Flag                        | Purpose                                                                                     |
|-----------------------------|---------------------------------------------------------------------------------------------|
| `-m, --mode {keystroke,clipboard,terminal}` | Where transcribed text goes (default `keystroke`). See [keyboard.md](keyboard.md). |
| `--typer {auto,eitype,pynput,wtype,ydotool}` | Keystroke-injection backend (default `auto`).                                |
| `--type-direct`             | In keystroke mode, type the transcription as keystrokes instead of synthesising Ctrl+V.     |
| `-o, --output-file FILE`    | Also append the transcription to this file.                                                 |

## Realtime (`gpt-realtime-whisper`)

| Flag                                              | Purpose                                                                                      |
|---------------------------------------------------|----------------------------------------------------------------------------------------------|
| `--realtime-delay {minimal,low,medium,high,xhigh}` | Trade off latency vs accuracy on `gpt-realtime-whisper` (default `medium`). Lower = faster partials but more paste churn in the focused window. |

This flag only affects the OpenAI realtime model; the other backends
ignore it.

## Silence detection (whisper, openai batch, groq)

| Flag                          | Default | Purpose                                                       |
|-------------------------------|---------|---------------------------------------------------------------|
| `--duration SECS`             | `120`   | Max recording duration in seconds.                            |
| `--silence SECS`              | `120`   | Silence duration in seconds that triggers a cut (default effectively disables it). |
| `--silence-db DB`             | `-200`  | Silence threshold in dB (default effectively disables it).    |
| `-a, --restart-after-silence` | off     | Resume recording after a silence-triggered transcription.     |

Streaming models (Vosk, `gpt-realtime-whisper`) ignore these — they
have their own end-of-utterance signal.

## Frontend

| Flag                        | Purpose                                                              |
|-----------------------------|----------------------------------------------------------------------|
| `--frontend {tray,terminal}` | UI to launch (default `tray`).                                       |
| `--no-prompt`               | In terminal mode, skip the interactive menu and record immediately.  |
| `--vosk-models M [M ...]`   | Vosk models offered in the tray menu.                                |
| `--whisper-models M [M ...]` | Whisper models offered in the tray menu.                             |

## Examples

Predefine the tray menu's Whisper / Vosk model lists:

```bash
scribe --vosk-models vosk-model-fr-0.22 \
       --whisper-models small large-v3-turbo
```

Cut on 2 s of silence below −40 dB and auto-restart afterwards:

```bash
scribe --silence-db -40 --silence 2 -a
```

Stream OpenAI realtime transcripts with the most aggressive latency
setting:

```bash
scribe --model gpt-realtime-whisper --realtime-delay minimal
```

Run scribe headlessly into a file without touching the clipboard or
focused window:

```bash
scribe --frontend terminal --no-prompt --mode terminal -o session.txt
```
