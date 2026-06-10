# Fine tuning & CLI reference

For a complete, always-current listing run:

```bash
scribe --help
```

The flags are grouped to mirror the source-of-truth in
[`scribe/app.py`](https://github.com/perrette/scribe/blob/main/scribe/app.py).

## Backend

| Flag                            | Purpose                                                                 |
|---------------------------------|-------------------------------------------------------------------------|
| `--backend {vosk,whisper,whisper-futo,openai,groq}` | Speech-recognition backend (prompted if omitted).            |
| `--model NAME`                  | Model name for the chosen backend. Auto-routes to the right backend for known model names (e.g. `--model gpt-realtime-whisper` selects `openai`). |
| `-l, --language LANG`           | Language alias selecting a preset Vosk model (`en`/`fr`/`de`/`it`), or `en` for English-only Whisper / Whisper-FUTO models. |
| `--download-folder-whisper DIR` | Folder to store Whisper models.                                         |
| `--download-folder-whisper-futo DIR` | Folder to store Whisper-FUTO ACFT ggml models (default: `$XDG_CACHE_HOME/whisper-futo`). |
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
also looks for `prompt.txt` and `words.txt` in the platform user-config
dir and loads them if they exist — handy for a long-lived personal
glossary. The path is resolved via `platformdirs`:

- Linux: `$XDG_CONFIG_HOME/scribe/` (default `~/.config/scribe/`)
- macOS: `~/Library/Application Support/scribe/`
- Windows: `%LOCALAPPDATA%\scribe\`

To suppress the default on a single invocation, pass an empty value:
`--prompt ""`, `--prompt-file ""`, or `--words` with no arguments. Each
flag suppresses only its own side (giving `--prompt ""` still loads
`words.txt` if present).

## Audio

| Flag                  | Purpose                                                  |
|-----------------------|----------------------------------------------------------|
| `--input-device N`    | Microphone device index (see `python -m sounddevice`).   |
| `--dry-run`           | Short-circuit the STT request boundary in every backend: model load is skipped and the network/SDK call returns a canned `[dry-run transcript]`. Used by the backend × mode smoke-test matrix; handy for plumbing without network access. |

## Output

| Flag                        | Purpose                                                                                     |
|-----------------------------|---------------------------------------------------------------------------------------------|
| `-m, --mode {keystroke,clipboard,terminal,file}` | Where transcribed text goes (default `keystroke`). `file` routes the transcript exclusively to `--output-file` and suppresses keyboard/clipboard output. See [output.md](output.md). |
| `--typer {auto,eitype,pynput,wtype,ydotool}` | Keystroke-injection backend (default `auto`).                                |
| `--type-direct`             | In keystroke mode, type the transcription as keystrokes instead of synthesising Ctrl+V.     |
| `-o, --output-file FILE`    | Path the transcription is appended to when `--mode file`. Defaults to `<user-desktop>/scribe-notes.txt` (the platform Desktop folder — `~/Desktop` on Linux/macOS, `%USERPROFILE%\Desktop` on Windows; falls back to home dir if Desktop is absent). Ignored when `--mode` is anything other than `file` (the four output modes are mutually exclusive). |

## Silence detection

> **Deprecated aliases** (still accepted, hidden from `--help`):
> `--duration N` maps to `--clip-timeout N`; `--silence-duration N`
> sets both `--stream-chunk-silence-break` and `--realtime-commit-silence`
> to `N`. Existing scripts using these flags continue to work.

## Voice activity detection

scribe ships two silence-detection backends. By default
(`--vad-mode auto`) it picks **silero-vad** when `onnxruntime` is
importable (always true on a stock `pip install scribe-cli` since
`onnxruntime` is a base dependency) and falls back to a plain dB
volume threshold otherwise. silero is much more robust to ambient
noise (clicks, fan, traffic) and to soft speech than dB, which drops
sub-threshold syllables and gets fooled by loud non-speech.

The dB and silero parameter groups are independent — the inactive
mode's knobs are ignored.

| Flag                          | Default | Purpose                                                                |
|-------------------------------|---------|------------------------------------------------------------------------|
| `--vad-mode {auto,db,silero}` | `auto`  | Silence-detection backend. `auto` picks silero when available, dB otherwise. |
| `--vad-threshold FLOAT`       | `0.5`   | **[silero only]** Speech-probability threshold in `[0,1]`. Lower = more permissive (catches quiet speech and more noise); higher = stricter. |
| `--vad-min-silence-ms INT`    | `300`   | **[silero only]** Minimum sustained low-probability span before speech-end fires, in ms. silero's onset/offset smoothing window. |
| `--silence-db DB`             | `-40`   | **[dB only]** dBFS volume floor for "this frame is silent". Ignored when silero is the active mode. |

## Realtime (`gpt-realtime-whisper`)

| Flag                                              | Default      | Purpose                                                                                                                                                                                  |
|---------------------------------------------------|--------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--realtime-delay {minimal,low,medium,high,xhigh}` | `medium`    | Trade off latency vs accuracy on `gpt-realtime-whisper`. Lower = faster partials but more paste churn in the focused window.                                                             |
| `--realtime-gate` / `--no-realtime-gate`          | on           | Drop silent frames (per the active `--vad-mode`) before sending them over the WebSocket so silent audio isn't billed as input tokens. |
| `--realtime-commit-silence SECS`                  | `0.6`        | Seconds of silence before a mid-session commit flushes trailing words to the server (default `0.6`). Set to `0` to rely solely on the server's turn detection. |

The tray's **Stream (advanced) › Stream** picker unifies `--realtime-gate`
and `--realtime-commit-silence` into a single choice: **Live** (gate
off, commit disabled — server turn detection only) or **Offline after
Xs** (gate on, commit after X seconds of silence). At the CLI level the
two flags remain independent. The auto-stop is documented under
**Listening mode → `--stream-timeout`** below (covers both native
streamers and pseudo-streaming on batch backends).

Streaming models (Vosk, `gpt-realtime-whisper`) ignore the batch
silence-chunking knobs; they have their own end-of-utterance signal.

## Listening mode

| Flag                              | Default | Purpose                                                                                   |
|-----------------------------------|---------|-------------------------------------------------------------------------------------------|
| `--stream`                        | —       | Force a batch backend (whisper, whisper-futo, openai non-realtime, groq) into pseudo-streaming — live chunks driven by `--stream-chunk-max` and `--stream-chunk-silence-break`. Same as the tray's **Mode: Stream**. |
| `--clip`                          | default | Transcribe the whole recording at end. Same as the tray's **Mode: Clip**.                 |
| `--stream-chunk-max SECS`         | `10`    | Maximum chunk duration in seconds. Force-cut fires at this threshold when no silence pause has been detected (default `10`). |
| `--stream-chunk-min SECS`         | `1.5`   | Minimum chunk size before a silence-cut is allowed (default `1.5`). Prevents very short clips that cause Whisper hallucinations. |
| `--stream-first-chunk-min SECS`   | `3.0`   | Minimum chunk size for the *first* chunk of a streaming thread (default `3.0`). Higher than `--stream-chunk-min` so the bootstrap chunk has enough audio for Whisper to produce a punctuated transcript whose tail seeds the rolling prompt for the rest. Applies on recording start and right after a context-reset silence. Inactive when `--stream-context-length 0`. Clamped to `≤ --stream-chunk-max`. Set equal to `--stream-chunk-min` to disable. |
| `--stream-chunk-silence-break SECS` | `0.6` | Silence duration that triggers a chunk cut (default `0.6`). Special value `0` enables Auto mode (best-silence-in-window at force-cut time). |
| `--stream-context-reset-silence X` | `3.0`  | Multiplier of `--stream-chunk-silence-break` above which the rolling cross-chunk prompt context is discarded (default `3.0`, i.e. 1.8 s at default silence-break). Use `inf` to never reset. |
| `--clip-timeout SECS`             | `600`   | Auto-stop after this many seconds in Clip mode (default `600`). |
| `--stream-timeout SECS`           | `None`  | Auto-stop after this many seconds in Stream mode (`None` = Always On, no auto-stop). Tray equivalent: **Stream timeout** in the Stream (advanced) submenu. |

Native streamers (vosk, `gpt-realtime-whisper`) are always streaming
and ignore `--clip`. `--realtime`, `--pseudo-streaming`,
`--streaming-window`, and `--realtime-timeout` are kept as hidden
back-compat aliases (`--streaming-window N` maps to
`--stream-chunk-max 2N` to preserve the old effective force-cut
threshold; `--realtime-timeout` maps to `--stream-timeout`).

## Frontend

| Flag                        | Purpose                                                              |
|-----------------------------|----------------------------------------------------------------------|
| `--frontend {tray,terminal}` | UI to launch (default `tray`).                                       |
| `--no-interactive`          | In terminal mode, skip the interactive menu and record immediately. |
| `--record`                  | Start recording immediately on launch, frontend-agnostic. In terminal it's a one-line shortcut for `--no-interactive`; in tray it auto-fires the Record action ~0.5 s after the icon comes up. Useful for hotkey bindings (`scribe --record` triggers a recording from anywhere) and batched / scripted invocations. |
| `--vosk-models M [M ...]`   | Vosk models offered in the tray menu.                                |
| `--whisper-models M [M ...]` | Whisper models offered in the tray menu.                             |
| `--whisper-futo-models M [M ...]` | Whisper-FUTO ACFT models offered in the tray menu.              |

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

**Batched / scripted use** — record one dictation headlessly, write
it where you want, exit. No tray, no menu, no clipboard:

```bash
# Append to a file (default <Desktop>/scribe-notes.txt — override with -o)
scribe --record --frontend terminal --mode file

# Same with a custom path
scribe --record --frontend terminal --mode file -o /tmp/notes.txt

# Pipe-friendly: transcript on stdout
scribe --record --frontend terminal --mode terminal

# Streamed: chunks appended live (as you speak) instead of all-at-once
# at end-of-recording. Useful for long dictations and tail-following:
#   tail -f /tmp/notes.txt
scribe --record --frontend terminal --mode file --stream -o /tmp/notes.txt
```

`--record` starts the recording immediately, `--frontend terminal`
skips the tray icon, `--mode file` (or `terminal`) picks where the
transcript lands, `--stream` (optional) emits chunks live instead of
the default Clip-mode all-at-once. Combine with a hotkey or cron for
one-shot capture.

Bias the recogniser toward domain jargon (medical terms, proper names):

```bash
scribe --prompt "Patient notes from a cardiology consult." \
       --words tachycardia bradycardia echocardiogram metoprolol
```

Or store the lists in files for reuse across sessions:

```bash
scribe --prompt-file ~/.config/scribe/prompt.txt \
       --words-file  ~/.config/scribe/words.txt
```
