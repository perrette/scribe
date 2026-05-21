from pathlib import Path
import tomllib
import signal
import argparse
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
    for name in ("groq", "openai", "whisper", "vosk"):
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
    """ choose a specialist version of a model if language is specified (whisper)"""

    if backend == "whisper" and language and language.lower() in ["en", "english"]:
        available_models_en = ["tiny.en", "base.en", "small.en", "medium.en", "large", "turbo"]
        if model + ".en" in available_models_en:
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

    if backend == "openai":
        return "gpt-4o-mini-transcribe"

    if backend == "groq":
        return "whisper-large-v3-turbo"

    raise ValueError(f"Unknown backend: {backend}")


def _resolve_prompt_and_words(prompt_text, prompt_file, words, words_file):
    """Read --prompt-file / --words-file from disk and merge with the inline
    flags. Returns ``(prompt_str_or_None, words_list_or_empty)``.

    Empty / whitespace-only inputs collapse to None / [] so backends can do a
    simple truthy check before adding the field to their request.
    """
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


def _build_backend_kwargs(backend, model, language, samplerate, duration,
                          silence_db, silence_duration, api_key,
                          download_folder_vosk, download_folder_whisper,
                          realtime_delay, realtime_gate,
                          pseudo_streaming, streaming_window,
                          prompt_text, words):
    # Cloud whisper variants (OpenAI batch, Groq, OpenAI realtime) take a
    # single `prompt` string — fold the word list into it. faster-whisper
    # gets the word list separately via `hotwords=` (dedicated biasing
    # channel), so we pass it through unmerged.
    merged_prompt = prompt_text
    if words and backend != "whisper":
        word_blob = " ".join(words)
        merged_prompt = f"{prompt_text} {word_blob}" if prompt_text else word_blob

    if backend == "vosk":
        # Vosk has no soft prompt; only a hard grammar. Silently ignore for now.
        return dict(model_name=model, language=language, samplerate=samplerate,
                    timeout=None, silence_duration=None,
                    model_kwargs={"download_root": download_folder_vosk})
    if backend == "whisper":
        return dict(model_name=model, language=language, samplerate=samplerate,
                    timeout=duration, silence_duration=silence_duration, silence_thresh=silence_db,
                    pseudo_streaming=pseudo_streaming, streaming_window=streaming_window,
                    prompt=prompt_text,
                    hotwords=(" ".join(words) if words else None),
                    model_kwargs={"download_root": download_folder_whisper})
    if backend in ("openai", "groq"):
        from scribe.backends.openai_api import REALTIME_MODELS
        kwargs = dict(model_name=model, samplerate=samplerate,
                      timeout=duration, silence_duration=silence_duration, silence_thresh=silence_db,
                      pseudo_streaming=pseudo_streaming, streaming_window=streaming_window,
                      api_key=api_key,
                      prompt=merged_prompt)
        if backend == "openai" and model in REALTIME_MODELS:
            kwargs["realtime_delay"] = realtime_delay
            kwargs["realtime_gate"] = realtime_gate
            # Pseudo-streaming is for batch backends; the realtime backend
            # already streams natively. Strip these so its __init__ doesn't
            # see options it doesn't act on.
            kwargs.pop("pseudo_streaming", None)
            kwargs.pop("streaming_window", None)
        return kwargs
    raise ValueError(f"Unknown backend: {backend}")


def get_transcriber(model=None, backend=None, dummy=False, interactive=True, language=None,
                    samplerate=None, duration=None,
                    silence_db=-40.0, silence_duration=0.6,
                    api_key=None, download_folder_vosk=None, download_folder_whisper=None,
                    realtime_delay="medium", realtime_gate=True,
                    pseudo_streaming=False, streaming_window=30.0,
                    prompt=None, prompt_file=None, words=None, words_file=None,
                    **kwargs):
    if dummy:
        return DummyTranscriber("whisper", "dummy")
    if model and not backend:
        if model.startswith("vosk-"):
            backend = "vosk"
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
    prompt_text, word_list = _resolve_prompt_and_words(prompt, prompt_file, words, words_file)
    backend_kwargs = _build_backend_kwargs(backend, model, language, samplerate, duration,
                                          silence_db, silence_duration, api_key,
                                          download_folder_vosk, download_folder_whisper,
                                          realtime_delay, realtime_gate,
                                          pseudo_streaming, streaming_window,
                                          prompt_text, word_list)
    try:
        return _build_transcriber(backend, **backend_kwargs)
    except Exception as error:
        print(error)
        print(f"Failed to (down)load model {model}.")
        exit(1)

def get_parser():

    parser = argparse.ArgumentParser()

    group = parser.add_argument_group("Backend")
    group.add_argument("--backend", choices=list(BACKENDS),
                       help="Speech-recognition backend (prompted if omitted).")
    group.add_argument("--model",
                       help="Model name for the chosen backend (see README).")
    group.add_argument("-l", "--language", choices=list(language_config["vosk"]),
                       help="Language alias selecting a preset vosk model, or 'en' for English-only whisper models.")
    group.add_argument("--api-key",
                       help="API key for cloud backends (openai, groq); falls back to OPENAI_API_KEY / GROQ_API_KEY.")
    group.add_argument("--download-folder-whisper", help="Folder to store Whisper models.")
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

    group = parser.add_argument_group("Output")
    group.add_argument("-m", "--mode",
                       choices=("keystroke", "clipboard", "terminal"),
                       default="keystroke",
                       help="Where transcribed text goes: keystroke (focused window), clipboard, or terminal (default: %(default)s).")
    group.add_argument("--typer", default="auto", type=str,
                       help="Keystroke-injection backend: auto, eitype, pynput, wtype, ydotool (default: %(default)s).")
    group.add_argument("--type-direct", action="store_true",
                       help="In keystroke mode, type the transcription as keystrokes instead of "
                            "synthesising Ctrl+V from the clipboard. Works in terminals where Ctrl+V "
                            "is the ^V control character. Cost: slower for long text; on wtype/ydotool "
                            "non-ASCII characters fall back to their ASCII equivalents (eitype is "
                            "Unicode-correct).")
    group.add_argument("-o", "--output-file",
                       help="Also append the transcription to this file.")

    group = parser.add_argument_group("Silence detection (shared)")
    group.add_argument("--duration", default=120, type=float,
                       help="Max recording duration in seconds (default: %(default)s).")
    group.add_argument("--silence-db", default=-40.0, type=float,
                       help="dBFS volume floor for 'this frame is silent' "
                            "(default: %(default)s). Used by every silence-driven "
                            "behavior (realtime gate, realtime auto-commit, "
                            "pseudo-streaming chunking).")
    group.add_argument("--silence-duration", default=0.6, type=float,
                       help="Seconds of silence required before triggering a "
                            "backend's silence behavior (default: %(default)s). "
                            "For the realtime backend: time before a mid-session "
                            "commit flushes trailing words. For pseudo-streaming "
                            "batch backends: candidate cut point within the "
                            "streaming window.")

    group = parser.add_argument_group("Realtime (gpt-realtime-whisper)")
    group.add_argument("--realtime-delay",
                       choices=("minimal", "low", "medium", "high", "xhigh"),
                       default="medium",
                       help="Trade off latency vs accuracy on gpt-realtime-whisper "
                            "(default: %(default)s; lower = faster partials but more "
                            "paste churn in the focused window).")
    group.add_argument("--realtime-gate", action=argparse.BooleanOptionalAction,
                       default=True,
                       help="Drop silent frames (per --silence-db) before sending "
                            "them over the WebSocket so silent audio isn't billed "
                            "as input tokens (default: on; pass --no-realtime-gate "
                            "to disable).")

    group = parser.add_argument_group("Pseudo-streaming (experimental)")
    group.add_argument("--pseudo-streaming", action="store_true",
                       help="[EXPERIMENTAL] Force a batch backend (whisper, groq, "
                            "openai non-realtime) into chunked pseudo-streaming "
                            "using --streaming-window and --silence-duration. "
                            "Off by default — the batch backend transcribes the "
                            "whole recording on stop.")
    group.add_argument("--streaming-window", default=30.0, type=float,
                       help="[EXPERIMENTAL] Target streaming window in seconds for "
                            "--pseudo-streaming (default: %(default)s). After this "
                            "many seconds of buffered audio, cut at the first "
                            "silence (>= --silence-duration); if no silence "
                            "arrives by 2x the window, force-cut.")

    group = parser.add_argument_group("Frontend")
    group.add_argument("--frontend", choices=["tray", "terminal"], default="tray",
                       help="UI to launch: tray (system tray icon) or terminal (default: %(default)s).")
    group.add_argument("--no-interactive", "--no-prompt", action="store_false", dest="interactive",
                       help="In terminal mode, skip the interactive menu and record immediately. "
                            "(--no-prompt is a deprecated alias kept for backward compatibility.)")
    group.add_argument("--vosk-models", nargs="*", default=vosk_models,
                       help="Vosk models offered in the tray menu.")
    group.add_argument("--whisper-models", nargs="*", default=whisper_models,
                       help="Whisper models offered in the tray menu.")

    return parser


# Commencer l'enregistrement
def start_recording(micro, session, mode="keystroke", typer="auto",
                    output_file=None, callback=None, type_direct=False, **greetings):
    """Drive a recording, dispatching the transcript to the destination implied
    by ``mode`` (the same three-way choice the tray exposes as Keyboard mode):

      - 'keystroke': land in the focused window. For streaming backends (vosk)
        each chunk is pasted live as it arrives; for batch backends the full
        text is pasted once at end-of-recording. With ``type_direct=True`` the
        chunks/text are typed as raw keystrokes instead of pasted from the
        clipboard — useful for terminals where Ctrl+V is the ^V control char.
      - 'clipboard': copy to clipboard, user pastes manually.
      - 'terminal':  no clipboard, no keystroke — text only printed.
    """
    if mode not in ("keystroke", "clipboard", "terminal"):
        raise ValueError(f"Unknown mode {mode!r} (expected keystroke|clipboard|terminal)")

    # Query the live transcriber instance — the registered class may dispatch
    # to a streaming sibling for specific models (e.g. openai →
    # gpt-realtime-whisper), so a class-level lookup via BACKENDS would lie.
    backend_obj = getattr(session, "backend", session)
    is_streaming = bool(getattr(backend_obj, "supports_streaming", False)) if not isinstance(backend_obj, str) else False
    # Clipboard is written in clipboard mode (the user pastes manually) and in
    # paste-based keystroke mode (the paste source). type_direct keystroke
    # mode bypasses the clipboard entirely — we type the chunks/text raw.
    do_clipboard = mode == "clipboard" or (mode == "keystroke" and not type_direct)
    do_live_paste = (mode == "keystroke") and is_streaming and not type_direct
    do_paste_at_end = (mode == "keystroke") and not is_streaming and not type_direct
    do_live_type = (mode == "keystroke") and is_streaming and type_direct
    do_type_at_end = (mode == "keystroke") and not is_streaming and type_direct

    if do_live_type or do_type_at_end:
        from scribe.typers import pick_typer
        _typer_obj = pick_typer(typer if typer != "auto" else None)
    else:
        _typer_obj = None

    if do_live_paste:
        from scribe.keyboard import paste_via_clipboard
        session.log("Live paste-per-chunk: each chunk lands in the focused window as it arrives.")
    elif do_live_type:
        assert _typer_obj is not None
        session.log(f"Live type-per-chunk via {_typer_obj.name}: each chunk is typed directly as it arrives.")

    if do_clipboard:
        import pyperclip
        session.log("The transcription will be copied to clipboard as it becomes available.")

    fulltext = ""

    for result in session.start_recording(micro, **greetings):

        if result.get('text'):
            clear_line()
            print(result.get('text'))
            # Backends own their own inter-chunk spacing — Vosk appends a
            # space to each phrase, gpt-realtime-whisper deltas already
            # carry leading whitespace per Whisper tokenization. The app
            # just concatenates verbatim.
            chunk_text = result['text']
            fulltext += chunk_text

            if output_file:
                with open(output_file, "a") as f:
                    f.write(result['text'] + "\n")

            if do_live_paste:
                # Live paste-per-chunk: copy this chunk to clipboard and fire
                # Ctrl+V. Universal Unicode support (clipboard handles any
                # codepoint) and orthogonal to typer choice (Ctrl+V is the
                # same keystroke regardless of layout).
                paste_via_clipboard(chunk_text, typer=typer,
                                     verify_iters=2, sleep_s=0.05)
            elif do_live_type:
                assert _typer_obj is not None
                _typer_obj.type(chunk_text)
            elif do_clipboard:
                pyperclip.copy(fulltext.strip())

        else:
            print_partial(result.get('partial', ''))

    if do_paste_at_end and fulltext.strip():
        from scribe.keyboard import paste_via_clipboard
        # Multi-chunk transcriptions (e.g. local whisper with silence-splitting)
        # called pyperclip.copy() many times during recording. wl-copy is async
        # on Wayland — paste_via_clipboard force-writes the final text and
        # polls until the clipboard reflects it before triggering Ctrl+V.
        paste_via_clipboard(fulltext.strip(), typer=typer)
    elif do_type_at_end and fulltext.strip():
        assert _typer_obj is not None
        _typer_obj.type(fulltext.strip())

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

    image = Image.open(Path(scribe_data.__file__).parent / "share" / "icon.png")
    image_recording = Image.open(Path(scribe_data.__file__).parent / "share" / "icon_recording.png")
    image_writing = Image.open(Path(scribe_data.__file__).parent / "share" / "icon_writing.png")

    if transcriber.backend == "vosk":
        # Recording and writing happen at the same time in this backend.
        image_recording = Image.alpha_composite(image_recording.convert("RGBA"), image_writing.convert("RGBA"))

    state_images = {
        None: image,
        "recording": image_recording,
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
            return "recording"
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
            print("Starting app...")
            app.run()
            return
        else:
            greetings = dict(start_message="Listening... Press Ctrl+C to stop.")
            start_recording(micro, state.session if state.session is not None else state.transcriber,
                            mode=o.mode, typer=o.typer, output_file=o.output_file,
                            type_direct=getattr(o, "type_direct", False),
                            **greetings)

        o.interactive = True
        o.backend = None
        o.model = None
        o.language = None

if __name__ == "__main__":
    main()