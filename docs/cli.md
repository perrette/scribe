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

## Prompting & vocabulary biasing

Bias the model toward particular names, jargon, or topics. Two
complementary knobs:

| Flag                     | Purpose                                                                                          |
|--------------------------|--------------------------------------------------------------------------------------------------|
| `--prompt TEXT`          | Free-text style / context hint shown to the model.                                               |
| `--prompt-file PATH`     | Reads the prompt from a file; appended to `--prompt` if both are given.                          |
| `--words W [W ...]`      | List of words to emphasise. Joined onto the prompt for cloud Whisper; routed to faster-whisper's dedicated `hotwords` channel locally. |
| `--words-file PATH`      | Whitespace-separated words from a file; merged with `--words`.                                   |

The whisper-family APIs cap the prompt around ~224 tokens; longer hints
are silently truncated. Vosk has no soft prompt and ignores both flags.
See [backends.md › Vocabulary biasing](backends.md#vocabulary-biasing)
for the per-backend wiring.

**Default files.** When none of the four flags above are given, scribe
also looks for `$XDG_CONFIG_HOME/scribe/prompt.txt` and
`$XDG_CONFIG_HOME/scribe/words.txt` (default
`~/.config/scribe/{prompt,words}.txt`) and loads them if they exist —
handy for a long-lived personal glossary. To suppress the default on a
single invocation, pass an empty value: `--prompt ""`, `--prompt-file
""`, or `--words` with no arguments. Each flag suppresses only its own
side (giving `--prompt ""` still loads `words.txt` if present).

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

## Silence detection (shared)

| Flag                       | Default | Purpose                                                                |
|----------------------------|---------|------------------------------------------------------------------------|
| `--duration SECS`          | `120`   | Max recording duration in seconds.                                     |
| `--silence-db DB`          | `-40`   | dBFS volume floor for "this frame is silent". Used by every silence-driven behavior. |
| `--silence-duration SECS`  | `0.6`   | How long silence must persist before triggering a backend's silence behavior (realtime auto-commit, pseudo-streaming cut). |

## Realtime (`gpt-realtime-whisper`)

| Flag                                              | Default  | Purpose                                                                                                                                                                                  |
|---------------------------------------------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--realtime-delay {minimal,low,medium,high,xhigh}` | `medium` | Trade off latency vs accuracy on `gpt-realtime-whisper`. Lower = faster partials but more paste churn in the focused window.                                                             |
| `--realtime-gate` / `--no-realtime-gate`          | on       | Drop silent frames (per `--silence-db`) before sending them over the WebSocket so silent audio isn't billed as input tokens. After `--silence-duration` of silence, also commit mid-session so trailing words flush live. |

Streaming models (Vosk, `gpt-realtime-whisper`) ignore the batch
silence-chunking knobs; they have their own end-of-utterance signal.

## Frontend

| Flag                        | Purpose                                                              |
|-----------------------------|----------------------------------------------------------------------|
| `--frontend {tray,terminal}` | UI to launch (default `tray`).                                       |
| `--no-interactive`          | In terminal mode, skip the interactive menu and record immediately. (`--no-prompt` is kept as a deprecated alias.) |
| `--vosk-models M [M ...]`   | Vosk models offered in the tray menu.                                |
| `--whisper-models M [M ...]` | Whisper models offered in the tray menu.                             |

## Examples

Predefine the tray menu's Whisper / Vosk model lists:

```bash
scribe --vosk-models vosk-model-fr-0.22 \
       --whisper-models small large-v3-turbo
```

Stream OpenAI realtime transcripts with the most aggressive latency
setting:

```bash
scribe --model gpt-realtime-whisper --realtime-delay minimal
```

Disable the realtime silence gate (e.g. to A/B against a noisy
environment) — you'll pay for silent audio while the session is open:

```bash
scribe --model gpt-realtime-whisper --no-realtime-gate
```

Run scribe headlessly into a file without touching the clipboard or
focused window:

```bash
scribe --frontend terminal --no-interactive --mode terminal -o session.txt
```

Bias the recogniser toward domain jargon (medical terms, proper names):

```bash
scribe --prompt "Patient notes from a cardiology consult." \
       --words tachycardia bradycardia echocardiogram metoprolol
```

Or store the lists in files for reuse across sessions:

```bash
scribe --prompt-file ~/.config/scribe/prompt.txt \
       --words-file  ~/.config/scribe/glossary.txt
```
