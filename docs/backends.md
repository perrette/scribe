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
[output.md](output.md) for how the keystroke mode interacts with
streaming models.

There are many [Vosk models](https://alphacephei.com/vosk/models)
available; a handful are pre-mapped to common languages (`en`, `fr`,
`de`, `it`) in
[`scribe/models.toml`](https://github.com/perrette/scribe/blob/main/scribe/models.toml). Pick one with
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
`whisper-large-v3-turbo`. **Extremely fast** thanks to Groq's
inference hardware — the recommended cloud backend by default, and
the natural pick for `--stream` mode where per-chunk roundtrip
latency dominates perceived speed:

```bash
export GROQ_API_KEY=YOURAPIKEY
scribe --backend groq          # Clip mode (default)
scribe --backend groq --stream # live transcription, per-chunk
```

The `groq` backend reuses the `openai` Python client under the hood, so
installing `[openai]` is enough for both.

## Stopping a recording

For batch models (Whisper local, Whisper-via-API, Groq, `gpt-4o-*`) the
recording continues until you stop it manually (Stop in the tray,
Ctrl+C in the terminal), with a safety stop after `--clip-timeout`
seconds (10 minutes by default) — the transcription happens once when
you stop. Silent pauses are capped at `--clip-max-silence` seconds
(2 by default) in the audio sent for transcription, so dead air does
not count toward what the cloud APIs bill by duration.

Streaming models (Vosk, `gpt-realtime-whisper`) emit partials as you
speak and stop on the same Stop / Ctrl+C action.

## Vocabulary biasing

`--prompt TEXT` and `--words W [W ...]` (plus the `--prompt-file` /
`--words-file` companions) bias the recogniser toward a particular
style, domain, or word list. The concept is generic across the
whisper-family backends but each backend exposes it slightly
differently:

| Backend                              | `--prompt`                    | `--words`                                              | `--language`                                           |
|--------------------------------------|-------------------------------|--------------------------------------------------------|---------------------------------------------------------|
| `whisper` (faster-whisper, local)    | passed as `initial_prompt=`   | passed as `hotwords=` — a **dedicated biasing channel** separate from the prompt | passed as `language=` (ISO 639-1); `-l en` also auto-substitutes `small.en` etc. |
| `whisper-futo` (pywhispercpp, local) | passed as `initial_prompt=`   | joined onto the prompt string (no separate hotwords channel here) | passed as `language=` (ISO 639-1); `-l en` auto-substitutes `small.en` etc. |
| `openai` batch (`gpt-4o*-transcribe`) | passed as `prompt=`           | joined onto the prompt string                          | passed as `language=` hint (ISO 639-1)                  |
| `groq` (`whisper-large-v3-turbo`)     | passed as `prompt=`           | joined onto the prompt string                          | passed as `language=` hint (ISO 639-1)                  |
| `openai` realtime (`gpt-realtime-whisper`) | *silently ignored* — the model rejects the prompt parameter server-side (HTTP 400 *"The 'prompt' parameter is not supported for this model."*). The kwarg stays accepted for plumbing compatibility but never reaches the API. | same — joined into the (ignored) prompt | passed as `language=` (ISO 639-1) |
| `vosk`                               | *ignored* (no soft prompt)    | *ignored* (Vosk only supports a hard `grammar` allowlist; not yet exposed) | picks a per-language model from `scribe/models.toml`; no runtime parameter |

The whisper-family APIs cap the prompt around ~224 tokens; longer
hints are silently truncated. Faster-whisper's `hotwords` channel is
the one place a separate "dictionary" really exists — everywhere else
`--words` is just a convenience to keep your word list out of the
prompt string in the CLI.

### Prompt style biases output style

Whisper mirrors the *style* of whatever prompt it receives. A
prompt like `"Tierney Comet"` (a bare wordlist) biases the model
toward unpunctuated, list-style output — sentences come out without
periods. A prompt like `"Tierney, Comet."` (or any prose ending in a
period) biases it toward punctuated output. Two practical
consequences:

- **`--prompt` is yours to control.** If your `prompt.txt` ends with
  a period and looks like a sentence, your transcripts will be
  punctuated. If it ends with a bare keyword, they probably won't.
  This effect is most visible in **Stream mode**, where Whisper sees
  short audio chunks and leans more heavily on the prompt for style
  cues.
- **`--words` is auto-formatted by scribe.** For backends that fold
  words into the prompt (`whisper-futo`, `openai`, `groq`), scribe
  renders the word list as `"word1, word2, …, wordN."` — comma-
  separated with a single terminal period — so your `words.txt` can
  stay a bare list with no special formatting and the bias still
  comes out punctuated. Stray punctuation on individual entries is
  stripped first, so `words.txt` content is normalised regardless of
  layout. On `whisper` (faster-whisper, local), words go to the
  dedicated `hotwords` channel and bypass the prompt entirely.

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

## Language

`-l / --language LANG` tells the backend which language to expect.
What that means in practice varies by backend (see the per-backend
column in the table above):

- **Whisper-family** (`whisper`, `whisper-futo`, `openai` batch +
  realtime, `groq`) — the language is passed to the model as a hard
  lock: the decoder generates that language regardless of what it
  hears acoustically. Accepts any [ISO 639-1 short code](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes)
  Whisper recognises (~99 languages). When unset, Whisper auto-detects
  per chunk.
- **English-only model variants** — for `whisper` and `whisper-futo`,
  `-l en` *also* auto-substitutes the English-only model when one
  exists (`small` → `small.en`, etc.). These variants trade
  multilingual coverage for English accuracy.
- **Vosk** — language isn't a runtime parameter; vosk ships a
  separate model per language. `-l fr` looks up the vosk model
  pre-mapped to French in [`scribe/models.toml`](https://github.com/perrette/scribe/blob/main/scribe/models.toml)
  and instantiates that one. Vosk has no auto-detect path, so the
  Language menu's `Auto` entry on vosk falls back to a sensible
  default — the tray shows `Auto (🇬🇧 en)` to make this explicit
  without mutating the stored `language=None`.

The tray's **Language** submenu exposes the four curated languages
(`en` / `fr` / `de` / `it`) with origin-country flag prefixes
(🇬🇧 / 🇫🇷 / 🇩🇪 / 🇮🇹). The CLI accepts these plus any other ISO 639-1
code the active backend recognises.

## Stream mode (works with any backend)

`--stream` (or **Mode: Stream** in the tray) emits transcribed text
**live as you speak**, regardless of which backend you picked. This
is the headline v1.0.0 improvement: scribe abstracts over the two
different mechanisms that backends use to deliver live output, so
`--stream` works uniformly across every supported backend.

- **Native streaming backends** (Vosk, `gpt-realtime-whisper`) push
  partial results from the server as audio is received — scribe just
  forwards them to the chosen output (focused window / clipboard /
  terminal / file). These backends are *always* in Stream mode; the
  Mode toggle reads "Mode: Stream (native)" for them and is read-only.
- **Batch backends** (Whisper local, Whisper FUTO, OpenAI
  `gpt-4o-*-transcribe`, Groq `whisper-large-v3-turbo`) don't accept
  partial audio. scribe instead cuts the recording buffer on
  detected silence and issues a separate transcription request for
  each chunk — internally called *pseudo-streaming*. The user sees
  the same live experience.

```bash
scribe --stream                       # any backend, live transcription
scribe --stream --backend groq        # Groq + Stream is the sweet spot
scribe --stream --backend whisper     # local, live, no API key
```

### How pseudo-streaming carves up a recording

Once the buffer has grown to at least `--stream-chunk-min` (default
1.5 s), silence of at least `--stream-chunk-silence-break` (default
0.6 s) triggers a chunk cut. A force-cut fires at `--stream-chunk-max`
(default 10 s) regardless of silence, to cap latency. The session
continues until you stop it manually.

The first chunk uses a higher floor (`--stream-first-chunk-min`,
default 3 s) so the bootstrap chunk has enough audio to seed the
rolling prompt for the rest. Auto-disabled when
`--stream-context-length 0` (Patient). If you stop talking before
the floor is reached, a pause past `--stream-context-reset-silence ×
--stream-chunk-silence-break` (default 1.8 s) flushes the buffer
anyway — your utterance is never stranded.

### Does pseudo-streaming change the API cost?

For cloud backends, going from one big transcription to N chunked
requests **does not normally change the bill**:

- **Groq** (`whisper-large-v3-turbo`) is billed per second of audio.
  Total audio is unchanged → same cost.
- **OpenAI `whisper-1`** (legacy) is billed per minute of audio. Same
  logic, same cost.
- **OpenAI `gpt-4o-transcribe` / `gpt-4o-mini-transcribe`** are token-
  billed (audio-in + text-out + prompt-in). Audio and output stay
  identical; the only delta is the rolling cross-chunk *prompt*
  context (~200 chars ≈ 50–60 tokens per chunk after the first).
  At gpt-4o-mini-transcribe input rates this is negligible — well
  under a cent per long session.

That said, your real cost depends on your usage and your account's
pricing tier — **verify on your provider's billing dashboard** if
cost is a hard constraint.

Two special values for `--stream-chunk-silence-break` (set via the
tray's **Silence break** picker or `--stream-chunk-silence-break 0`
at the CLI):

- **Auto** (`0`) — disables the fixed-threshold trigger. At force-cut
  time scribe picks the *longest* silence interval within the window
  whose start position is at least `--stream-chunk-min` into the chunk,
  re-cutting there for a more natural word boundary. Falls back to a
  brute force-cut if no qualifying silence is found.
- **Max** — disables silence-based cuts entirely; only the force-cut at
  `--stream-chunk-max` fires. Useful when you want uniform chunk sizes
  regardless of speech patterns. (Only selectable from the tray picker.)

Stream mode is off by default — the default `Clip` mode transcribes the
whole recording at end (`--clip`). The tray menu surfaces the same
toggle as the top-level **Mode: Stream / Clip** item. Native
streamers (vosk, `gpt-realtime-whisper`) are always streaming and the
menu shows **Mode: Stream (native)** for them.

### Cross-chunk prompt context

In Stream mode (pseudo-streaming) scribe automatically augments
each chunk's prompt with the trailing ~200 characters of the
*previous* chunk's transcription. This rolling tail is concatenated
onto whatever static `--prompt` / `--words` you configured and
reaches the backend through the same channel as the static prompt
(the vocabulary biasing table above). The motivation is cross-chunk
continuity:

- **Capitalization drift** — without context, a chunk that starts
  right after a period might come back lowercased.
- **Article gender (FR/IT/ES/…)** — `"la nouveau"` → `"le nouveau"`
  once the prior chunk has established the noun.
- **Language lock** — `whisper.cpp` auto-detects language per call;
  feeding the previous chunk's tokens keeps the language stable
  across cuts.

Whisper's prompt window is capped at ~224 tokens; 200 chars of French
sits well under that and leaves room for your static prompt + words
list.

The rolling tail is **dropped** when the silence between two
utterances exceeds `--stream-context-reset-silence` ×
`--stream-chunk-silence-break` (default 3 × 0.6 s = 1.8 s) — a long
pause is treated as a new sentence/idea boundary, where carrying a
possibly-bad prior chunk forward biases the next one more than it
helps. Use `--stream-context-reset-silence inf` to keep context across
arbitrarily long pauses.

Short pauses (mid-sentence punctuation) keep the context; the cut at
the start of every new recording also clears it.

### Streaming recipes — two profiles

The defaults stream phrases in as you talk; the Patient profile waits
for natural pauses and transcribes one utterance at a time. They make
opposite trade-offs around the same fundamental tension: short audio
windows give Whisper less to work with, so cross-chunk *context*
matters more in Balanced, less in Patient.

#### Balanced (default)

```bash
scribe --stream
```

Phrases commit every ~10 s or on a 0.6 s pause, with a 200-char
rolling prompt carrying earlier text forward as context for each new
chunk. Whisper sees short audio windows in isolation; the rolling
context partially compensates by telling the model what was just
said. Good live-feel, small per-chunk accuracy hit vs. Patient.

#### Patient (auto-clip)

```bash
scribe --stream \
       --stream-chunk-min 0.5 \
       --stream-chunk-max 300 \
       --stream-chunk-silence-break 2 \
       --stream-context-length 0
```

Each utterance is a complete self-contained sentence. scribe waits
for a 2 s pause, transcribes the whole thing at once, then waits for
the next one. No rolling context (`context-length 0`) because each
chunk is already a full utterance — there's nothing short to
compensate for. Highest per-chunk accuracy; no text appears until
you finish talking.
