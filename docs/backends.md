# Backends in detail

Scribe ships five speech-to-text backends. They are all picked through
the same `--backend` / `--model` CLI flags (or the **Model** submenu in
the tray / terminal frontend). Whether a transcription is *streaming*
(text appears live as you speak) or *batch* (text arrives at end of
recording) depends on the **model** chosen — not the backend.

## At a glance

| Backend                | `--backend`     | Default model              | Streaming model(s)        | Requires                                |
|------------------------|-----------------|----------------------------|---------------------------|-----------------------------------------|
| Groq (cloud)           | `groq`          | `whisper-large-v3-turbo`   | —                         | `GROQ_API_KEY`                          |
| OpenAI (cloud)         | `openai`        | `gpt-4o-mini-transcribe`   | `gpt-realtime-whisper`    | `OPENAI_API_KEY`                        |
| Whisper FUTO (local)   | `whisper-futo`  | `small`                    | —                         | `pip install scribe-cli[whisper-futo]`  |
| Whisper (local)        | `whisper`       | `small`                    | —                         | `pip install scribe-cli[whisper]`       |
| Vosk (local)           | `vosk`          | language-dependent         | all Vosk models           | `pip install scribe-cli[vosk]`          |

Run `scribe` without arguments and it picks the first backend whose
dependency / API key is present, preferring cloud over local and the
faster local option first:
`groq → openai → whisper-futo → whisper → vosk`.

## `whisper-futo` (local, fast on short dictations)

Runs locally via [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
(through [`pywhispercpp`](https://github.com/absadiki/pywhispercpp))
using [FUTO's ACFT-finetuned models](https://github.com/futo-org/whisper-acft).
ACFT (Audio Context Fine-Tuning) lets the encoder run on the actual
audio length instead of always padding to 30 s — a meaningful speedup
on short dictations, which is the typical scribe workload.

The available models offered in the tray menu are
`tiny / base / small`. FUTO has not released ACFT weights for
`medium / large / turbo`; for those sizes use the `whisper` backend.

With `--language en` (or `-l en`) scribe auto-substitutes the
English-only variant (e.g. `small` → `small.en`) when it exists.

Models are auto-downloaded on first use from `voiceinput.futo.org`
to `$XDG_CACHE_HOME/whisper-futo/` (override with
`--download-folder-whisper-futo`).

For audio ≥ 30 s the ACFT speedup tapers off and the encoder window
collapses to the standard 30 s; quality and speed in that regime are
similar to the `whisper` backend. Pick `whisper-futo` if most of your
dictations are short, the `whisper` backend if you regularly do
multi-minute recordings or need `medium` / `large` / `turbo`.

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

Streaming models (Vosk, `gpt-realtime-whisper`) emit partials as you
speak and stop on the same Stop / Ctrl+C action.

## Vocabulary biasing

`--prompt TEXT` and `--words W [W ...]` (plus the `--prompt-file` /
`--words-file` companions) bias the recogniser toward a particular
style, domain, or word list. The concept is generic across the
whisper-family backends but each backend exposes it slightly
differently:

| Backend                              | `--prompt`                    | `--words`                                              |
|--------------------------------------|-------------------------------|--------------------------------------------------------|
| `whisper` (faster-whisper, local)    | passed as `initial_prompt=`   | passed as `hotwords=` — a **dedicated biasing channel** separate from the prompt |
| `openai` batch (`gpt-4o*-transcribe`) | passed as `prompt=`           | joined onto the prompt string                          |
| `groq` (`whisper-large-v3-turbo`)     | passed as `prompt=`           | joined onto the prompt string                          |
| `openai` realtime (`gpt-realtime-whisper`) | included in the session config as `transcription.prompt` | joined onto the prompt string |
| `vosk`                               | *ignored* (no soft prompt)    | *ignored* (Vosk only supports a hard `grammar` allowlist; not yet exposed) |

The whisper-family APIs cap the prompt around ~224 tokens; longer
hints are silently truncated. Faster-whisper's `hotwords` channel is
the one place a separate "dictionary" really exists — everywhere else
`--words` is just a convenience to keep your word list out of the
prompt string in the CLI.

Both flags read from the corresponding `*-file` argument when present.
Inline + file inputs are combined.

```bash
# Inline
scribe --prompt "ML systems infra: K8s, etcd, Envoy." \
       --words kubectl envoyproxy etcdctl

# From files (handy for long-lived glossaries)
scribe --prompt-file ~/.config/scribe/prompt.txt \
       --words-file  ~/.config/scribe/words.txt
```

When *no* prompt/words flag is given, scribe also auto-loads
`prompt.txt` and `words.txt` from the platform user-config dir
(`~/.config/scribe/` on Linux, `~/Library/Application Support/scribe/`
on macOS, `%LOCALAPPDATA%\scribe\` on Windows — resolved via
`platformdirs`) if they exist. To suppress the default for one
invocation, pass an explicit empty value: `--prompt ""` (or
`--prompt-file ""`) suppresses the prompt default; `--words` with no
arguments (or `--words-file ""`) suppresses the words default. Each
side is independent.

## Pseudo-streaming (experimental)

`--pseudo-streaming` makes a batch backend behave streaming-like by
cutting the running buffer into chunks driven by silence:

```bash
scribe --pseudo-streaming --streaming-window 5
```

After `--streaming-window` seconds of buffered audio, scribe cuts at
the first silence of at least `--silence-duration` and transcribes the
chunk; if no silence arrives by `2 × --streaming-window`, it
force-cuts. The session continues until you stop it. Default `5` s
trades a little Whisper context for snappier "text appears as you
speak" UX; raise it (10–30 s) if accuracy on long sentences matters
more than latency.

This is experimental and off by default. The tray menu surfaces the
same toggle under Options ▶ Advanced ▶ Pseudo-streaming.
