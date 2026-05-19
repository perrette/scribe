# Backends in detail

Scribe ships four speech-to-text backends. They are all picked through
the same `--backend` / `--model` CLI flags (or the **Model** submenu in
the tray / terminal frontend). Whether a transcription is *streaming*
(text appears live as you speak) or *batch* (text arrives at end of
recording) depends on the **model** chosen — not the backend.

## At a glance

| Backend         | `--backend` | Default model              | Streaming model(s)        | Requires                            |
|-----------------|-------------|----------------------------|---------------------------|-------------------------------------|
| Groq (cloud)    | `groq`      | `whisper-large-v3-turbo`   | —                         | `GROQ_API_KEY`                      |
| OpenAI (cloud)  | `openai`    | `gpt-4o-mini-transcribe`   | `gpt-realtime-whisper`    | `OPENAI_API_KEY`                    |
| Whisper (local) | `whisper`   | `small`                    | —                         | `pip install scribe-cli[whisper]`   |
| Vosk (local)    | `vosk`      | language-dependent         | all Vosk models           | `pip install scribe-cli[vosk]`      |

Run `scribe` without arguments and it picks the first backend whose
dependency / API key is present, preferring cloud over local:
`groq → openai → whisper → vosk`.

## `whisper` (local)

Runs locally via
[`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) and
defaults to the `small` model. Excellent at full-utterance
transcription in
[many languages](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages),
but it does not stream — text appears at end-of-recording — and
execution time depends on model size and hardware.

The available models offered in the tray menu are
`tiny / base / small / medium / large-v3 / large-v3-turbo`. Larger
models trade speed for accuracy.

With `--language en` (or `-l en`) scribe auto-substitutes the
English-only variant (e.g. `small` → `small.en`) when it exists.

## `vosk` (local, streaming)

Vosk transcribes in real time and is very good at one language at a
time, but tends to make more mistakes than Whisper and does not produce
punctuation. It becomes really useful in longer, interactive sessions
where the live "appears as you speak" UX matters — see
[keyboard.md](keyboard.md) for how the keystroke mode interacts with
streaming models.

There are many [Vosk models](https://alphacephei.com/vosk/models)
available; a handful are pre-mapped to common languages (`en`, `fr`,
`de`, `it`) in
[`scribe/models.toml`](../scribe/models.toml). Pick one with
`-l <lang>` or browse the full list interactively from the menu.

## `openai` (OpenAI cloud)

The OpenAI backend supports three models:

- `gpt-4o-mini-transcribe` *(default)* — fast, low-cost batch
  transcription.
- `gpt-4o-transcribe` — higher-quality batch transcription.
- `gpt-realtime-whisper` *(streaming)* — partial transcripts arrive
  as you speak. Same UX as Vosk but using OpenAI's cloud model.

All three share the same `OPENAI_API_KEY` and the `[openai]` extra; no
extra dependencies. Set the key once:

```bash
export OPENAI_API_KEY=YOURAPIKEY
scribe --backend openai                          # default: gpt-4o-mini-transcribe
scribe --model gpt-4o-transcribe                 # batch, higher quality
scribe --model gpt-realtime-whisper              # streaming
```

`--model` alone auto-routes to the `openai` backend for any of the
three models above, so `--backend openai` is optional.

### `--realtime-delay` (gpt-realtime-whisper only)

The streaming model has a latency-vs-accuracy knob exposed as
`--realtime-delay {minimal,low,medium,high,xhigh}` (default `medium`).
Lower values emit partial transcripts sooner — at the cost of more
revisions arriving in the focused window. Higher values batch tokens
into longer chunks so what gets pasted is more stable.

See OpenAI's
[gpt-realtime-whisper model card](https://developers.openai.com/api/docs/models/gpt-realtime-whisper)
for the full picture.

## `groq` (Groq cloud)

Talks to Groq's OpenAI-compatible API and defaults to
`whisper-large-v3-turbo`. Typically the fastest cloud option for
full-utterance transcription:

```bash
export GROQ_API_KEY=YOURAPIKEY
scribe --backend groq
```

The `groq` backend reuses the `openai` Python client under the hood, so
installing `[openai]` is enough for both.

## Stopping a recording

For batch models (Whisper local, Whisper-via-API, Groq, `gpt-4o-*`) the
recording continues for up to 2 minutes until you stop it manually
(Stop in the tray, Ctrl+C in the terminal) — the transcription happens
once when you stop.

You can also auto-cut on silence:

```bash
scribe --silence-db -40 --silence 2
```

cuts the recording when a silence below −40 dB lasts more than 2
seconds. The defaults (`--silence-db -200`, `--silence 120`) effectively
disable this and keep full manual control.

Streaming models (Vosk, `gpt-realtime-whisper`) emit partials as you
speak and stop on the same Stop / Ctrl+C action — there is no silence
threshold to tune.
