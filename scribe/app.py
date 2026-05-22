import os
from pathlib import Path
import tomllib
import signal
import argparse
import platformdirs
from scribe.audio import Microphone
from scribe.util import print_partial, clear_line, prompt_choices, ansi_link, colored
from scribe.backends import BACKENDS, available_backends, probe_backend, get_transcriber as _build_transcriber
from scribe.session import RecordingSession
from desktop_ai_core.frontends.tray import MultiStateTrayIcon, write_pidfile, register_signal_toggle
from desktop_ai_core.frontends.dialog import show_error_dialog
from scribe.menu import build_menu, AppState, _menu_to_pystray, format_model_label

with open(Path(__file__).parent / "models.toml", "rb") as f:
    language_config_default = tomllib.load(f)

language_config = language_config_default.copy()


def get_default_backend():
    for name in ("groq", "openai", "whisper-futo", "whisper", "vosk"):
        ok, _ = probe_backend(name)
        if ok:
            return name
    raise RuntimeError(
        "No STT backend available. "
        "Set GROQ_API_KEY for Groq, OPENAI_API_KEY for OpenAI, "
        "or install Whisper (local) via `pip install faster-whisper` "
        "or Vosk (local) via `pip install vosk`."
    )

UNAVAILABLE_BACKENDS = []


def pick_specialist_model(model, language, backend):
    """ choose a specialist version of a model if language is specified (whisper, whisper-futo)"""

    if backend == "whisper" and language and language.lower() in ["en", "english"]:
        available_models_en = ["tiny.en", "base.en", "small.en", "medium.en", "large", "turbo"]
        if model + ".en" in available_models_en:
            model += ".en"

    if backend == "whisper-futo" and language and language.lower() in ["en", "english"]:
        if model + ".en" in whisper_futo_english_models:
            model += ".en"

    return model


class DummyTranscriber:

    def __init__(self, backend, model_name):
        self.backend = backend
        self.model_name = model_name

    def start_recording(self, micro, **kwargs):
        while True:
            try:
                yield {"text": input()}
            except KeyboardInterrupt:
                break

    def __getattr__(self, item):
        return None

whisper_models = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
whisper_english_models = ["tiny.en", "base.en", "small.en", "medium.en"]
# FUTO ACFT publishes only tiny/base/small (+ .en variants). Community
# conversions exist for large/turbo but their large-v3 encoder is
# incompatible with the audio_ctx shrinkage that's the point of this
# backend — for large models use the `whisper` backend instead.
whisper_futo_models = ["tiny", "base", "small"]
whisper_futo_english_models = ["tiny.en", "base.en", "small.en"]
whisperapi_models = ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "gpt-realtime-whisper"]
vosk_models = [language_config["vosk"][lang]["model"] for lang in language_config["vosk"]]


def _prompt_model_for_backend(backend, language, interactive):
    if backend == "vosk":
        available_languages = list(language_config[backend])
        if language:
            if language not in available_languages:
                print(f"Language '{language}' is not pre-defined (yet) for backend '{backend}'.")
                print(f"Yet it may actually exist.")
                print(f"Please choose the model explictly from {ansi_link('https://alphacephei.com/vosk/models')}.")
                print(f"Or pick one of the pre-defined languages: ", " ".join(available_languages))
                exit(1)
            choices = [language_config[backend][language]["model"]]
            default_model = choices[0]
        else:
            available_models = [language_config[backend][lang]["model"] for lang in available_languages]
            choices = list(zip(available_models, available_languages)) + [f" * [Any model from {ansi_link('https://alphacephei.com/vosk/models')}]"]
            default_model = choices[0]
        if interactive:
            print(f"For information about vosk models see: {ansi_link('https://alphacephei.com/vosk/models')}")
            return prompt_choices(choices, default=default_model, label="model")
        return default_model[0] if isinstance(default_model, tuple) else default_model

    if backend == "whisper":
        default_model = "small"
        if interactive:
            print(f"See {ansi_link('https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages')} for available models.")
            model = prompt_choices(whisper_models, default=default_model, label="model",
                                    hidden_models=whisper_english_models)
        else:
            model = default_model
        return pick_specialist_model(model, language, backend)

    if backend == "whisper-futo":
        default_model = "small"
        if interactive:
            print(f"FUTO ACFT models — fast on short dictations. See {ansi_link('https://github.com/futo-org/whisper-acft')}.")
            model = prompt_choices(whisper_futo_models, default=default_model, label="model",
                                    hidden_models=whisper_futo_english_models)
        else:
            model = default_model
        return pick_specialist_model(model, language, backend)

    if backend == "openai":
        return "gpt-4o-mini-transcribe"

    if backend == "groq":
        return "whisper-large-v3-turbo"

    raise ValueError(f"Unknown backend: {backend}")


# Default config dir for prompt.txt / words.txt auto-discovery. Uses
# platformdirs so the path matches each OS's convention:
#   Linux:   $XDG_CONFIG_HOME/scribe  (default ~/.config/scribe)
#   macOS:   ~/Library/Application Support/scribe
#   Windows: %LOCALAPPDATA%\scribe
SCRIBE_CONFIG_DIR = platformdirs.user_config_dir("scribe")
DEFAULT_PROMPT_FILE = os.path.join(SCRIBE_CONFIG_DIR, "prompt.txt")
DEFAULT_WORDS_FILE = os.path.join(SCRIBE_CONFIG_DIR, "words.txt")

# Default sink for `--mode file` when the user hasn't passed `-o`.
# Desktop is more visible than ~/Documents — picked so a new user
# trying File mode immediately sees the transcript file on their
# desktop. `platformdirs.user_desktop_dir()` resolves XDG_DESKTOP_DIR
# on Linux, ~/Desktop on macOS, %USERPROFILE%\Desktop on Windows,
# and falls back to the home dir if Desktop is missing.
DEFAULT_OUTPUT_FILE = os.path.join(platformdirs.user_desktop_dir(), "scribe-notes.txt")


def autodiscover_prompt_files(o):
    """Persist auto-discovered ``prompt.txt`` / ``words.txt`` defaults into
    the argparse namespace ``o`` so downstream consumers (the tray menu's
    "Prompt file: …" label, the runtime reload helper) can read them as
    first-class state instead of re-deriving the defaults. Mirrors the
    fallback condition in :func:`_resolve_prompt_and_words` exactly: only
    fires when both the inline flag and the file flag are *unset* — passing
    ``--prompt ""`` / ``--prompt-file ""`` still suppresses the default.
    ``o.prompt`` / ``o.prompt_file`` (and the words counterparts) are
    expected to exist (argparse fills them with ``None``); missing attrs
    are tolerated for tests that build minimal namespaces."""
    if (getattr(o, "prompt", None) is None
            and getattr(o, "prompt_file", None) is None
            and os.path.exists(DEFAULT_PROMPT_FILE)):
        o.prompt_file = DEFAULT_PROMPT_FILE
        print(f"Using default prompt file: {DEFAULT_PROMPT_FILE}")
    if (getattr(o, "words", None) is None
            and getattr(o, "words_file", None) is None
            and os.path.exists(DEFAULT_WORDS_FILE)):
        o.words_file = DEFAULT_WORDS_FILE
        print(f"Using default words file: {DEFAULT_WORDS_FILE}")


def _resolve_prompt_and_words(prompt_text, prompt_file, words, words_file):
    """Read --prompt-file / --words-file from disk and merge with the inline
    flags. Returns ``(prompt_str_or_None, words_list_or_empty)``.

    When neither inline arg nor an explicit file is provided, falls back
    to ``$XDG_CONFIG_HOME/scribe/{prompt,words}.txt`` (default
    ``~/.config/scribe/``) if those files exist. Passing an empty string
    (e.g. ``--prompt ""`` or ``--prompt-file ""``) counts as an explicit
    "no, leave it empty" and suppresses the default-file lookup — argparse
    distinguishes "flag omitted" (``None``) from "flag given an empty
    value" (``""``).

    Empty / whitespace-only inputs collapse to None / [] so backends can do a
    simple truthy check before adding the field to their request.
    """
    if prompt_text is None and prompt_file is None and os.path.exists(DEFAULT_PROMPT_FILE):
        prompt_file = DEFAULT_PROMPT_FILE
        print(f"Using default prompt file: {prompt_file}")
    if words is None and words_file is None and os.path.exists(DEFAULT_WORDS_FILE):
        words_file = DEFAULT_WORDS_FILE
        print(f"Using default words file: {words_file}")
    if prompt_file:
        with open(prompt_file) as f:
            file_text = f.read().strip()
        if file_text:
            prompt_text = f"{prompt_text}\n{file_text}" if prompt_text else file_text
    if words_file:
        with open(words_file) as f:
            file_words = f.read().split()
        words = list(words or []) + file_words
    words = [w for w in (words or []) if w]
    return (prompt_text or None), words


_WORD_STRIP_CHARS = " \t\r\n.,;:!?"


def _format_words_for_prompt(words):
    """Render a `--words` list as a punctuated string suitable for joining
    into a Whisper-family prompt. ``["Tierney", "Comet"]`` → ``"Tierney,
    Comet."``. Trailing period biases the model toward emitting periods
    of its own (Whisper mirrors prompt style); comma separator avoids the
    "every word is its own sentence" look. Strips any stray punctuation
    the user may have left on individual entries so the output is well-
    formed regardless of input. Returns ``""`` for an empty list."""
    cleaned = [w.strip(_WORD_STRIP_CHARS) for w in (words or [])]
    cleaned = [w for w in cleaned if w]
    if not cleaned:
        return ""
    return ", ".join(cleaned) + "."


def compose_prompt_for_backend(backend, prompt_text, words):
    """Compose ``(prompt, hotwords)`` for a backend, applying the words-
    auto-format rule. faster-whisper has a dedicated `hotwords` channel so
    we keep words separate and untouched; every other prompt-using backend
    (whisper-futo / openai / groq) gets words folded into the prompt as a
    punctuated sentence so the prompt style biases Whisper toward
    punctuated output. Returns ``(None, None)`` when both sides are empty
    so callers can skip the kwarg entirely."""
    if backend == "whisper":
        return ((prompt_text or None),
                (" ".join(words) if words else None))
    words_blob = _format_words_for_prompt(words)
    if prompt_text and words_blob:
        merged = f"{prompt_text} {words_blob}"
    else:
        merged = prompt_text or words_blob
    return ((merged or None), None)


def _build_backend_kwargs(backend, model, language, samplerate, duration,
                          silence_db, stream_chunk_silence_break, realtime_commit_silence,
                          vad_mode, vad_threshold, vad_min_silence_ms,
                          download_folder_vosk, download_folder_whisper,
                          download_folder_whisper_futo,
                          realtime_delay, realtime_gate,
                          pseudo_streaming, stream_chunk_max,
                          stream_chunk_min, stream_context_reset_silence,
                          stream_context_length,
                          prompt_text, words, dry_run=False, debug=False):
    composed_prompt, composed_hotwords = compose_prompt_for_backend(backend, prompt_text, words)

    vad_kwargs = dict(vad_mode=vad_mode, vad_threshold=vad_threshold,
                      vad_min_silence_ms=vad_min_silence_ms)
    if backend == "vosk":
        # Vosk has no soft prompt; only a hard grammar. Silently ignore for now.
        return dict(model_name=model, language=language, samplerate=samplerate,
                    timeout=None,
                    model_kwargs={"download_root": download_folder_vosk},
                    dry_run=dry_run, debug=debug)
    if backend == "whisper":
        return dict(model_name=model, language=language, samplerate=samplerate,
                    timeout=duration,
                    stream_chunk_silence_break=stream_chunk_silence_break,
                    realtime_commit_silence=realtime_commit_silence,
                    silence_thresh=silence_db,
                    pseudo_streaming=pseudo_streaming, stream_chunk_max=stream_chunk_max,
                    stream_chunk_min=stream_chunk_min,
                    stream_context_reset_silence=stream_context_reset_silence,
                    stream_context_length=stream_context_length,
                    prompt=composed_prompt,
                    hotwords=composed_hotwords,
                    model_kwargs={"download_root": download_folder_whisper},
                    dry_run=dry_run, debug=debug,
                    **vad_kwargs)
    if backend == "whisper-futo":
        # pywhispercpp 1.4.1 exposes `initial_prompt`; the backend folds
        # words+prompt into it (and adds a rolling chunk-tail in
        # pseudo-streaming). No separate hotwords channel here — fold
        # everything into the prompt like the cloud backends do.
        return dict(model_name=model, language=language, samplerate=samplerate,
                    timeout=duration,
                    stream_chunk_silence_break=stream_chunk_silence_break,
                    realtime_commit_silence=realtime_commit_silence,
                    silence_thresh=silence_db,
                    pseudo_streaming=pseudo_streaming, stream_chunk_max=stream_chunk_max,
                    stream_chunk_min=stream_chunk_min,
                    stream_context_reset_silence=stream_context_reset_silence,
                    stream_context_length=stream_context_length,
                    prompt=composed_prompt,
                    download_folder=download_folder_whisper_futo,
                    dry_run=dry_run, debug=debug,
                    **vad_kwargs)
    if backend in ("openai", "groq"):
        from scribe.backends.openai_api import REALTIME_MODELS
        kwargs = dict(model_name=model, samplerate=samplerate,
                      timeout=duration,
                      stream_chunk_silence_break=stream_chunk_silence_break,
                      realtime_commit_silence=realtime_commit_silence,
                      silence_thresh=silence_db,
                      pseudo_streaming=pseudo_streaming, stream_chunk_max=stream_chunk_max,
                      stream_chunk_min=stream_chunk_min,
                      stream_context_reset_silence=stream_context_reset_silence,
                      stream_context_length=stream_context_length,
                      prompt=composed_prompt,
                      dry_run=dry_run, debug=debug,
                      **vad_kwargs)
        if backend == "openai" and model in REALTIME_MODELS:
            kwargs["realtime_delay"] = realtime_delay
            kwargs["realtime_gate"] = realtime_gate
            # Pseudo-streaming is for batch backends; the realtime backend
            # already streams natively. Strip these so its __init__ doesn't
            # see options it doesn't act on.
            kwargs.pop("pseudo_streaming", None)
            kwargs.pop("stream_chunk_max", None)
        return kwargs
    raise ValueError(f"Unknown backend: {backend}")


def get_transcriber(model=None, backend=None, dummy=False, interactive=True, language=None,
                    samplerate=None, clip_timeout=120.0, stream_timeout=None,
                    silence_db=None, stream_chunk_silence_break=0.6, realtime_commit_silence=0.6,
                    vad_mode="auto", vad_threshold=0.5, vad_min_silence_ms=300,
                    download_folder_vosk=None, download_folder_whisper=None,
                    download_folder_whisper_futo=None,
                    realtime_delay="medium", realtime_gate=True,
                    pseudo_streaming=False, stream_chunk_max=10.0,
                    stream_chunk_min=1.5, stream_context_reset_silence=3.0,
                    stream_context_length=200,
                    prompt=None, prompt_file=None, words=None, words_file=None,
                    dry_run=False, debug=False, **kwargs):
    if dummy:
        return DummyTranscriber("whisper", "dummy")
    if model and not backend:
        if model.startswith("vosk-"):
            backend = "vosk"
        # whisper-futo and whisper share model names (tiny/small/etc.) — model
        # alone can't disambiguate, so unqualified short names default to the
        # existing `whisper` backend. Use --backend whisper-futo (or pick from
        # the menu) to opt into the FUTO path.
        elif model in whisper_models + whisper_english_models:
            backend = "whisper"
        elif model in whisperapi_models:
            backend = "openai"
    if not backend:
        backends_list = list(BACKENDS)
        preferred = get_default_backend()
        backend = preferred if not interactive else prompt_choices(backends_list, preferred, "backend", UNAVAILABLE_BACKENDS)
    print(f"Selected backend: {backend}")
    if model:
        model = pick_specialist_model(model, language, backend)
    else:
        model = _prompt_model_for_backend(backend, language, interactive)
    print(f"Selected model: {model}")
    # silence_db is the single volume floor used by the dB fallback. Silero
    # mode ignores it. Default -40 dBFS — keeps the gate simple by design.
    if silence_db is None:
        silence_db = -40.0
    duration = stream_timeout if pseudo_streaming else clip_timeout
    prompt_text, word_list = _resolve_prompt_and_words(prompt, prompt_file, words, words_file)
    backend_kwargs = _build_backend_kwargs(backend, model, language, samplerate, duration,
                                          silence_db, stream_chunk_silence_break,
                                          realtime_commit_silence,
                                          vad_mode, vad_threshold, vad_min_silence_ms,
                                          download_folder_vosk, download_folder_whisper,
                                          download_folder_whisper_futo,
                                          realtime_delay, realtime_gate,
                                          pseudo_streaming, stream_chunk_max,
                                          stream_chunk_min, stream_context_reset_silence,
                                          stream_context_length,
                                          prompt_text, word_list, dry_run=dry_run, debug=debug)
    try:
        return _build_transcriber(backend, **backend_kwargs)
    except Exception as error:
        print(error)
        print(f"Failed to (down)load model {model}.")
        exit(1)

class _SilenceDurationAction(argparse.Action):
    """Hidden back-compat alias: --silence-duration N sets both
    stream_chunk_silence_break and realtime_commit_silence to N."""
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, "stream_chunk_silence_break", values)
        setattr(namespace, "realtime_commit_silence", values)


class _DurationAction(argparse.Action):
    """Hidden back-compat alias: --duration N sets clip_timeout = N."""
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, "clip_timeout", values)


def get_parser():

    parser = argparse.ArgumentParser()

    group = parser.add_argument_group("Backend")
    group.add_argument("--backend", choices=list(BACKENDS),
                       help="Speech-recognition backend (prompted if omitted).")
    group.add_argument("--model",
                       help="Model name for the chosen backend (see README).")
    group.add_argument("-l", "--language", choices=list(language_config["vosk"]),
                       help="Language alias selecting a preset vosk model, or 'en' for English-only whisper models.")
    group.add_argument("--download-folder-whisper", help="Folder to store Whisper models.")
    group.add_argument("--download-folder-whisper-futo",
                       help="Folder to store FUTO ACFT ggml models "
                            "(default: $XDG_CACHE_HOME/whisper-futo).")
    group.add_argument("--download-folder-vosk", help="Folder to store Vosk models.")
    group.add_argument("--prompt",
                       help="Free-text hint shown to the model to bias style/vocabulary "
                            "(whisper, openai, groq, realtime). Capped around ~224 tokens "
                            "by the whisper API; longer hints are silently truncated.")
    group.add_argument("--prompt-file",
                       help="Path to a text file whose contents are appended to --prompt.")
    group.add_argument("--words", nargs="*",
                       help="Words to bias the model toward. On faster-whisper they go to "
                            "the dedicated `hotwords` channel; on openai/groq/realtime they "
                            "are joined and appended to --prompt. Ignored by vosk.")
    group.add_argument("--words-file",
                       help="Path to a file with whitespace-separated words; merged with --words.")

    group = parser.add_argument_group("Audio")
    group.add_argument("--input-device", dest="input_device", type=int,
                       help="Microphone device index (see `python -m sounddevice`).")
    group.add_argument("--samplerate", default=16000, type=int, help=argparse.SUPPRESS)
    group.add_argument("--dummy", action="store_true", help=argparse.SUPPRESS)
    group.add_argument("--dry-run", action="store_true", dest="dry_run",
                       help="Short-circuit the STT request boundary in every "
                            "backend: model load is skipped and the network/SDK "
                            "call is replaced with a canned '[dry-run transcript]'. "
                            "Used by tests/test_backend_matrix.py to exercise the "
                            "recording pipeline without network access or every "
                            "model on disk.")
    group.add_argument("--debug", action="store_true", dest="debug",
                       help="Log one line per STT request (model, language, "
                            "prompt, audio length) for diagnosing transcription "
                            "issues.")

    group = parser.add_argument_group("Output")
    group.add_argument("-m", "--mode",
                       choices=("keystroke", "clipboard", "terminal", "file"),
                       default="keystroke",
                       help="Where transcribed text goes: keystroke (focused window), "
                            "clipboard, terminal, or file (requires --output-file; "
                            "default: %(default)s).")
    group.add_argument("--typer", default="auto", type=str,
                       help="Keystroke-injection backend: auto, eitype, pynput, wtype, ydotool (default: %(default)s).")
    group.add_argument("--type-direct", action="store_true",
                       help="In keystroke mode, type the transcription as keystrokes instead of "
                            "synthesising Ctrl+V from the clipboard. Works in terminals where Ctrl+V "
                            "is the ^V control character. Cost: slower for long text; on wtype/ydotool "
                            "non-ASCII characters fall back to their ASCII equivalents (eitype is "
                            "Unicode-correct).")
    group.add_argument("-o", "--output-file",
                       default=DEFAULT_OUTPUT_FILE,
                       help=f"Path the transcription is appended to when "
                            f"--mode file is active. Default: {DEFAULT_OUTPUT_FILE}. "
                            f"Ignored when --mode is something else (the four "
                            f"output modes are mutually exclusive).")

    group = parser.add_argument_group("Silence detection")
    group.add_argument("--duration", type=float,
                       action=_DurationAction, default=argparse.SUPPRESS,
                       help=argparse.SUPPRESS)
    group.add_argument("--silence-duration", type=float,
                       action=_SilenceDurationAction, default=argparse.SUPPRESS,
                       help=argparse.SUPPRESS)

    group = parser.add_argument_group("Voice activity detection")
    group.add_argument("--vad-mode", choices=("auto", "db", "silero"), default="auto",
                       help="Silence-detection backend (default: %(default)s). "
                            "'auto' picks silero if installed, dB otherwise. "
                            "'silero' uses silero-vad — much more robust to "
                            "ambient noise (ticks, fan, traffic) AND to soft "
                            "speech (the dB gate drops sub-threshold syllables; "
                            "silero recognises speech spectrally). "
                            "'db' is a volume-threshold fallback used when "
                            "onnxruntime is unavailable (see --silence-db). "
                            "The dB and silero parameter groups are independent.")
    group.add_argument("--vad-threshold", default=0.5, type=float,
                       help="[silero only] Speech-probability threshold in [0,1] "
                            "(default: %(default)s). Lower = more permissive (catches "
                            "quiet speech but also more noise); higher = stricter.")
    group.add_argument("--vad-min-silence-ms", default=300, type=int,
                       help="[silero only] Minimum sustained low-probability span before "
                            "speech-end is emitted, in ms (default: %(default)s). "
                            "Acts as silero's onset/offset smoothing window.")
    group.add_argument("--silence-db", default=None, type=float,
                       help="[dB only] Silence floor in dBFS for the dB-mode "
                            "fallback (default: -40). Ignored when "
                            "--vad-mode=silero (or =auto and silero is "
                            "available).")

    group = parser.add_argument_group("Realtime (gpt-realtime-whisper)")
    group.add_argument("--realtime-delay",
                       choices=("minimal", "low", "medium", "high", "xhigh"),
                       default="medium",
                       help="Trade off latency vs accuracy on gpt-realtime-whisper "
                            "(default: %(default)s; lower = faster partials but more "
                            "paste churn in the focused window).")
    group.add_argument("--realtime-gate", action=argparse.BooleanOptionalAction,
                       default=True,
                       help="Drop silent frames (per the active --vad-mode) before "
                            "sending them over the WebSocket so silent audio "
                            "isn't billed as input tokens (default: on; pass "
                            "--no-realtime-gate to disable).")
    group.add_argument("--realtime-commit-silence", default=0.6, type=float,
                       help="Seconds of silence before a mid-session commit flushes "
                            "trailing words to the gpt-realtime-whisper server "
                            "(default: %(default)s). Ignored for non-realtime backends.")

    group = parser.add_argument_group("Listening mode")
    mode_group = group.add_mutually_exclusive_group()
    mode_group.add_argument("--stream", dest="listen_mode", action="store_const",
                            const="stream",
                            help="Force a batch backend (whisper, whisper-futo, "
                                 "openai non-realtime, groq) into chunked "
                                 "pseudo-streaming using --stream-chunk-max and "
                                 "--stream-chunk-silence-break. Equivalent to the tray's "
                                 "'Mode: Stream'. Native streamers (vosk, "
                                 "gpt-realtime-whisper) are always streaming.")
    mode_group.add_argument("--clip", dest="listen_mode", action="store_const",
                            const="clip",
                            help="Transcribe the whole recording at end (default). "
                                 "Equivalent to the tray's 'Mode: Clip'.")
    # Hidden backward-compat aliases for --stream.
    mode_group.add_argument("--realtime", dest="listen_mode", action="store_const",
                            const="stream", help=argparse.SUPPRESS)
    group.add_argument("--pseudo-streaming", action="store_true",
                       help=argparse.SUPPRESS)
    group.add_argument("--stream-chunk-max", default=10.0, type=float,
                       dest="stream_chunk_max",
                       help="Maximum chunk duration in seconds for --stream mode "
                            "on batch backends (default: %(default)s). Force-cut "
                            "fires at this threshold when no silence pause has "
                            "triggered a commit.")
    group.add_argument("--streaming-window", type=lambda s: 2.0 * float(s),
                       dest="stream_chunk_max", default=argparse.SUPPRESS,
                       help=argparse.SUPPRESS)
    group.add_argument("--stream-chunk-min", default=1.5, type=float,
                       help="Minimum chunk size in seconds before a silence-cut "
                            "is allowed in --stream mode (default: %(default)s). "
                            "Prevents very short clips that cause Whisper hallucinations.")
    group.add_argument("--stream-chunk-silence-break", default=0.6, type=float,
                       help="Seconds of silence that triggers a chunk cut in "
                            "--stream mode (default: %(default)s). The cut fires once "
                            "a pause of this duration is detected and the buffer "
                            "exceeds --stream-chunk-min.")
    group.add_argument("--stream-context-reset-silence", default=3.0, type=float,
                       help="Multiplier of --stream-chunk-silence-break above which the "
                            "rolling cross-chunk prompt context is discarded in --stream mode "
                            "(default: %(default)s×). Use 'inf' to never reset context.")
    group.add_argument("--stream-context-length", default=200, type=int,
                       help="Max character length of the rolling cross-chunk prompt "
                            "context fed back to each new chunk in --stream mode "
                            "(default: %(default)s). 0 disables the rolling context "
                            "entirely — each chunk is transcribed without any "
                            "cross-chunk prompt.")
    group.add_argument("--clip-timeout", default=120.0, type=float,
                       help="Auto-stop Clip recording after this many seconds "
                            "(default: %(default)s).")
    group.add_argument("--stream-timeout", default=None, type=float,
                       help="Auto-stop Stream recording after this many seconds "
                            "(default: always on — no auto-stop).")
    # Hidden back-compat alias kept from when Stream mode was called Realtime.
    group.add_argument("--realtime-timeout", dest="stream_timeout", type=float,
                       default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    group = parser.add_argument_group("Frontend")
    group.add_argument("--frontend", choices=["tray", "terminal"], default="tray",
                       help="UI to launch: tray (system tray icon) or terminal (default: %(default)s).")
    group.add_argument("--no-interactive", "--no-prompt", action="store_false", dest="interactive",
                       help="In terminal mode, skip the interactive menu and record immediately.")
    group.add_argument("--record", action="store_true",
                       help="Start recording immediately on launch, no UI. Sugar for "
                            "'--frontend terminal --no-interactive'. Useful for batched / "
                            "scripted invocations (e.g. bound to a hotkey or run from cron). "
                            "Pair with --mode file or --mode terminal to control where the "
                            "transcript lands.")
    group.add_argument("--vosk-models", nargs="*", default=vosk_models,
                       help="Vosk models offered in the tray menu.")
    group.add_argument("--whisper-models", nargs="*", default=whisper_models,
                       help="Whisper models offered in the tray menu.")
    group.add_argument("--whisper-futo-models", nargs="*", default=whisper_futo_models,
                       help="FUTO ACFT Whisper models offered in the tray menu.")

    return parser


def _detect_is_streaming(session):
    """Detect whether the live backend behind ``session`` emits chunks
    (streaming or pseudo-streaming) or a single end-of-recording transcript.

    The registered class may dispatch to a streaming sibling for specific
    models (e.g. openai → gpt-realtime-whisper), so a class-level lookup
    via BACKENDS would lie — query the live instance instead.
    """
    backend_obj = getattr(session, "backend", session)
    if isinstance(backend_obj, str):
        return False
    return (
        bool(getattr(backend_obj, "supports_streaming", False))
        or bool(getattr(backend_obj, "pseudo_streaming", False))
    )


def _output_signature(o):
    """Snapshot of every ``o`` attribute the Output dispatch depends on.

    Compared on the chunk boundary so the recording loop can rebuild the
    Output when the tray menu toggles Output mode / typer / type_direct /
    output_file mid-recording.
    """
    return (
        getattr(o, "mode", "keystroke"),
        getattr(o, "typer", None),
        getattr(o, "type_direct", False),
        getattr(o, "output_file", None),
    )


def _resolve_output(o, *, is_streaming, backend_obj):
    """Build an Output from the live ``o`` Namespace.

    Centralised so the live-switch handler in :func:`start_recording`
    rebuilds via the same path as the initial construction.
    """
    from scribe.output import make_output
    mode = getattr(o, "mode", "keystroke")
    return make_output(
        mode=mode,
        typer=getattr(o, "typer", None) if mode == "keystroke" else None,
        type_direct=getattr(o, "type_direct", False),
        output_file=getattr(o, "output_file", None) if mode == "file" else None,
        is_streaming=is_streaming,
        backend_obj=backend_obj,
    )


# Commencer l'enregistrement
def start_recording(micro, session, o, callback=None, **greetings):
    """Drive a recording, dispatching the transcript to the destination implied
    by ``o.mode`` (the four-way Output radio in the tray):

      - 'keystroke': land in the focused window. For streaming backends (vosk)
        each chunk is pasted live as it arrives; for batch backends the full
        text is pasted once at end-of-recording. With ``o.type_direct=True``
        the chunks/text are typed as raw keystrokes instead of pasted from the
        clipboard — useful for terminals where Ctrl+V is the ^V control char.
      - 'clipboard': copy to clipboard, user pastes manually.
      - 'terminal':  no clipboard, no keystroke — text only printed.
      - 'file':      append to ``o.output_file`` only — keyboard/clipboard
                     output is suppressed. Requires ``o.output_file``.

    The output destination is resolved from ``o`` on every chunk boundary:
    if the user flips Output mode / Backend / Input mode via the tray menu
    mid-recording the next chunk lands in the new sink without restart.
    """
    backend_obj = getattr(session, "backend", session)
    is_streaming = _detect_is_streaming(session)

    output = _resolve_output(o, is_streaming=is_streaming, backend_obj=backend_obj)
    last_signature = _output_signature(o)

    # Log the initial wiring — matches the previous diagnostic lines so
    # users tailing the journal see the same hints.
    mode = getattr(o, "mode", "keystroke")
    type_direct = bool(getattr(o, "type_direct", False))
    if mode == "keystroke" and is_streaming and not type_direct:
        session.log("Live paste-per-chunk: each chunk lands in the focused window as it arrives.")
    elif mode == "keystroke" and is_streaming and type_direct:
        from scribe.output import KeyboardOutput
        if isinstance(output, KeyboardOutput) and output.typer_obj is not None:
            session.log(
                f"Live type-per-chunk via {output.typer_obj.name}: "
                "each chunk is typed directly as it arrives."
            )
    if mode == "clipboard" or (mode == "keystroke" and not type_direct):
        session.log("The transcription will be copied to clipboard as it becomes available.")

    fulltext = ""

    for result in session.start_recording(micro, **greetings):
        # Detect live-switch: if any output-affecting attr changed since
        # the last chunk, rebuild the Output. Rebuild on the boundary so
        # this chunk lands in the NEW destination.
        sig = _output_signature(o)
        if sig != last_signature:
            try:
                output = _resolve_output(o, is_streaming=is_streaming,
                                         backend_obj=backend_obj)
                last_signature = sig
            except ValueError as exc:
                # Fall back to the previous Output and revert o.mode to
                # whatever the last-known-good signature said. Keeps the
                # recording alive instead of crashing on the user's mid-
                # session menu toggle (e.g. switching to File without a
                # path set).
                session.notify_error("Output", str(exc))
                o.mode = last_signature[0]
                # Don't update last_signature — next chunk will see the
                # reverted o.mode and skip the rebuild branch.

        if result.get('text'):
            clear_line()
            print(result.get('text'))
            chunk_text = result['text']
            # Some backends own their inter-chunk spacing (Vosk appends a
            # trailing space per phrase, gpt-realtime-whisper deltas carry
            # leading whitespace per Whisper tokenization), BUT pseudo-
            # streaming chunks from whisper / whisper-futo / openai batch /
            # groq are standalone transcriptions with no padding. If the
            # running text doesn't end in whitespace and this chunk doesn't
            # start with whitespace, insert a separator — otherwise the
            # sentence boundary collapses into "...hello.How are you?".
            if fulltext and fulltext[-1:].strip() and chunk_text[:1].strip():
                chunk_text = " " + chunk_text
            fulltext += chunk_text
            output.on_chunk(chunk_text, fulltext)
        else:
            print_partial(result.get('partial', ''))

    output.on_finalize(fulltext)

    if callback:
        callback()



def create_app(micro, app_state):
    """Construct the system-tray pystray Icon from the unified menu spec.

    The menu tree is produced by ``build_menu(app_state)`` and converted to
    pystray's MenuItem hierarchy via ``_menu_to_pystray``. All recording and
    model-switching behavior lives on ``app_state``; ``create_app`` only wires
    the icon, image state machine, signal handlers, and pidfile.
    """
    import pystray
    from PIL import Image

    import scribe_data

    transcriber = app_state.transcriber
    session = RecordingSession(backend=transcriber, error_callback=show_error_dialog)
    app_state.session = session

    # Source PNGs are 406×406 high-res; most system tray hosts expect
    # ~16–32 px and either scale poorly or render at native size. Pre-
    # scale here so the tray icon matches OS conventions everywhere.
    _TRAY_ICON_SIZE = 32

    def _load_tray_icon(name):
        img = Image.open(Path(scribe_data.__file__).parent / "share" / name)
        img.thumbnail((_TRAY_ICON_SIZE, _TRAY_ICON_SIZE), Image.LANCZOS)
        return img

    image = _load_tray_icon("icon.png")
    image_recording = _load_tray_icon("icon_recording.png")
    image_writing = _load_tray_icon("icon_writing.png")
    # Composite (red + writing 'a'): shown while recording AND the silence
    # gate says speech is active. Gives the user a visual confirmation that
    # the audio is actually being captured/sent — not just sitting in
    # detected silence. Plain red = recording but waiting for speech.
    image_recording_active = Image.alpha_composite(
        image_recording.convert("RGBA"), image_writing.convert("RGBA"),
    )

    if transcriber.backend == "vosk":
        # vosk transcribes while recording — both recording sub-states show
        # the composite (no meaningful "waiting" since vosk streams
        # continuously).
        image_recording = image_recording_active

    state_images = {
        None: image,
        "recording": image_recording,
        "recording_active": image_recording_active,
        "busy": image_writing,
    }

    menu_spec = build_menu(app_state)
    pystray_menu = _menu_to_pystray(menu_spec, app_state)

    title = f"scribe — {format_model_label(transcriber.backend, transcriber.model_name)}"
    icon = pystray.Icon('scribe', image, title, pystray_menu)
    icon._model_selection = False
    icon._transcriber = transcriber
    icon._session = session
    icon._loading = False  # set True during background model-swap; reuses busy image

    def _get_icon_state():
        if getattr(icon, "_loading", False):
            return "busy"
        s = icon._session
        if s.recording:
            # session.waiting flips True after silence_duration of detected
            # silence, False on the first non-silent chunk. The composite
            # ("recording_active") tells the user audio is actually being
            # sent to the backend — solves the "is it hearing me?" question
            # without printing partial transcripts to the tray.
            return "recording" if s.waiting else "recording_active"
        if s.busy:
            return "busy"
        return None

    icon._state_machine = MultiStateTrayIcon(icon, state_images, _get_icon_state)

    app_state.bind_tray(icon, micro)

    write_pidfile("scribe")

    if hasattr(signal, "SIGUSR1"):
        register_signal_toggle(signal.SIGUSR1, lambda: app_state.cb_record(icon, None))
    if hasattr(signal, "SIGUSR2"):
        register_signal_toggle(signal.SIGUSR2,
                               lambda: icon._session.busy and app_state.cb_cancel(icon, None))

    return icon


_MODE_DESCRIPTION = {
    "keystroke": "Send to focused window (clipboard + Ctrl+V or live paste)",
    "clipboard": "Clipboard only (press Ctrl+V yourself)",
    "terminal":  "Terminal only",
}


def _print_main_status(state, o):
    t = state.transcriber
    print(f"Model [{colored(t.model_name, 'light_blue', attrs=['bold'])}] "
          f"from [{colored(t.backend, 'light_blue', attrs=['bold'])}] selected.")
    mode = getattr(o, "mode", "keystroke")
    mode_str = colored(mode, "light_blue", attrs=["bold"])
    print(f"Mode: {mode_str} — {_MODE_DESCRIPTION.get(mode, '?')}")
    if getattr(o, "output_file", None):
        print(f"Also writing to file: {colored(o.output_file, 'light_blue')}")
    if o.frontend == "tray":
        print(colored("App mode (tray) enabled", "light_green"))
    extras = [opt for opt in ("pseudo_streaming",) if getattr(o, opt, False)]
    if extras:
        print(f"Options: {' | '.join(colored(e, 'light_blue') for e in extras)}")


def main(args=None):
    parser = get_parser()
    o = parser.parse_args(args)

    # Surface auto-discovered prompt.txt / words.txt defaults on the
    # namespace before downstream consumers read it. Without this, the
    # tray menu's "Prompt file: …" / "Words file: …" labels show "(none)"
    # even when scribe is actively biasing on a default file — the file
    # was being loaded by `_resolve_prompt_and_words`, but the resolved
    # path stayed local to that function and never propagated to `o`.
    autodiscover_prompt_files(o)

    # Reconcile --stream / --clip with the legacy --pseudo-streaming flag.
    # --stream / --clip win when present; otherwise the existing
    # --pseudo-streaming boolean drives the default.
    listen_mode = getattr(o, "listen_mode", None)
    if listen_mode == "stream":
        o.pseudo_streaming = True
    elif listen_mode == "clip":
        o.pseudo_streaming = False
    # else: leave o.pseudo_streaming alone (default False, or True if
    # --pseudo-streaming was passed).

    # --record: skip the menu and start recording immediately. Affects
    # both frontends — for terminal it short-circuits the interactive
    # menu (same effect as --no-interactive); for tray the auto-fire is
    # scheduled on a small delay below, after the icon's event loop is
    # up. Frontend-agnostic by design — the user picks tray or terminal
    # independently.
    if getattr(o, "record", False):
        o.interactive = False

    # Resolve "auto" to a concrete typer name at startup so the menu can show
    # the actually-selected backend (not a meta "Auto" entry) and we don't
    # re-probe on every recording. If the explicit choice is unavailable
    # (e.g. eitype was uninstalled since last launch), fall back to auto-probe.
    from scribe.typers import pick_typer as _pick_typer
    try:
        if o.typer == "auto":
            o.typer = _pick_typer(None).name
        else:
            o.typer = _pick_typer(o.typer).name
    except (KeyError, RuntimeError):
        try:
            o.typer = _pick_typer(None).name
        except RuntimeError:
            o.typer = "auto"  # leave for type_text/paste_via_clipboard to surface
    if o.typer == "auto":
        print(colored("Typer: none available", "light_red"))
    else:
        print(f"Typer: {colored(o.typer, 'light_blue', attrs=['bold'])}")

    micro = Microphone(samplerate=o.samplerate, device=o.input_device)

    state = AppState(transcriber=None, session=None, o=o, error_callback=show_error_dialog)

    while True:
        if state.transcriber is None:
            # In tray mode the icon menu is the interactive surface, so suppress
            # backend/model prompts and let get_transcriber pick sensible defaults.
            transcriber_kwargs = vars(o).copy()
            if o.frontend == "tray":
                transcriber_kwargs["interactive"] = False
            state.transcriber = get_transcriber(**transcriber_kwargs)
            state.session = None
        if state.session is None and not isinstance(state.transcriber, DummyTranscriber):
            state.session = RecordingSession(backend=state.transcriber)

        _print_main_status(state, o)

        if o.frontend == "terminal" and o.interactive:
            build_menu(state)(state, None)
            if state.transcriber is None:
                continue

        if o.frontend == "tray":
            app = create_app(micro, state)
            if getattr(o, "record", False):
                # Auto-fire the Record action shortly after the icon's
                # event loop comes up. Daemon thread so it can't block
                # shutdown if the icon never reaches a ready state.
                import threading
                threading.Timer(
                    0.5,
                    lambda: state.cb_record(None, None),
                ).start()
            print("Starting app...")
            app.run()
            return
        else:
            greetings = dict(start_message="Listening... Press Ctrl+C to stop.")
            start_recording(micro, state.session if state.session is not None else state.transcriber,
                            o, **greetings)

        o.interactive = True
        o.backend = None
        o.model = None
        o.language = None

if __name__ == "__main__":
    main()