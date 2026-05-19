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
    for name in ("whisper", "groq", "openai", "vosk"):
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
whisperapi_models = ["gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
vosk_models = [language_config["vosk"][lang]["model"] for lang in language_config["vosk"]]


def _prompt_model_for_backend(backend, language, prompt):
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
        if prompt:
            print(f"For information about vosk models see: {ansi_link('https://alphacephei.com/vosk/models')}")
            return prompt_choices(choices, default=default_model, label="model")
        return default_model[0] if isinstance(default_model, tuple) else default_model

    if backend == "whisper":
        default_model = "small"
        if prompt:
            print(f"See {ansi_link('https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages')} for available models.")
            model = prompt_choices(whisper_models, default=default_model, label="model",
                                    hidden_models=whisper_english_models)
        else:
            model = default_model
        return pick_specialist_model(model, language, backend)

    if backend == "openai":
        return "gpt-4o-mini-transcribe"

    raise ValueError(f"Unknown backend: {backend}")


def _build_backend_kwargs(backend, model, language, samplerate, duration, silence, silence_db,
                          restart_after_silence, api_key, download_folder_vosk, download_folder_whisper):
    if backend == "vosk":
        return dict(model_name=model, language=language, samplerate=samplerate,
                    timeout=None, silence_duration=None,
                    model_kwargs={"download_root": download_folder_vosk})
    if backend == "whisper":
        return dict(model_name=model, language=language, samplerate=samplerate,
                    timeout=duration, silence_duration=silence, silence_thresh=silence_db,
                    restart_after_silence=restart_after_silence,
                    model_kwargs={"download_root": download_folder_whisper})
    if backend == "openai":
        return dict(model_name=model, samplerate=samplerate,
                    timeout=duration, silence_duration=silence, silence_thresh=silence_db,
                    restart_after_silence=restart_after_silence, api_key=api_key)
    raise ValueError(f"Unknown backend: {backend}")


def get_transcriber(model=None, backend=None, dummy=False, prompt=True, language=None,
                    samplerate=None, duration=None, silence=None, silence_db=None, restart_after_silence=None,
                    api_key=None, download_folder_vosk=None, download_folder_whisper=None, **kwargs):
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
        backend = preferred if not prompt else prompt_choices(backends_list, preferred, "backend", UNAVAILABLE_BACKENDS)
    print(f"Selected backend: {backend}")
    if model:
        model = pick_specialist_model(model, language, backend)
    else:
        model = _prompt_model_for_backend(backend, language, prompt)
    print(f"Selected model: {model}")
    backend_kwargs = _build_backend_kwargs(backend, model, language, samplerate, duration, silence,
                                          silence_db, restart_after_silence, api_key,
                                          download_folder_vosk, download_folder_whisper)
    try:
        return _build_transcriber(backend, **backend_kwargs)
    except Exception as error:
        print(error)
        print(f"Failed to (down)load model {model}.")
        exit(1)

def get_parser():

    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=list(BACKENDS),
                        help="Choose the backend to use for speech recognition (will be prompted otherwise).")

    parser.add_argument("--model",
                        help="""For vosk, any model from https://alphacephei.com/vosk/models,
                        e.g. 'vosk-model-small-en-us-0.15'.
                        For whisper, see https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages""")

    parser.add_argument("-l", "--language", choices=list(language_config["vosk"]),
                        help="An alias for preselected models when using the vosk backend, or 'en' for the English version of whisper models.")

    parser.add_argument("--dummy", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--frontend", choices=["tray", "terminal"], default="tray",
                        help="Which frontend to launch. Default: tray (system tray icon). "
                        "Use 'terminal' for the interactive TUI / one-shot recording mode.")
    parser.add_argument("--no-prompt", action="store_false", dest="prompt",
                        help="In terminal mode, skip the interactive menu and jump straight to recording.")

    parser.add_argument("--samplerate", default=16000, type=int, help=argparse.SUPPRESS)
    parser.add_argument("--input-device", dest="input_device", type=int,
                        help="The device index of the microphone to use.")

    group = parser.add_argument_group("transcription output")
    group.add_argument("-m", "--mode",
                       choices=("keystroke", "clipboard", "terminal"),
                       default="keystroke",
                       help="Where the transcription goes — mirrors the tray menu's "
                            "Keyboard mode radio. 'keystroke' (default): land in the "
                            "focused window — paste-per-chunk for streaming backends "
                            "(vosk), single Ctrl+V at end for batch backends "
                            "(whisper, openai, groq). 'clipboard': copy to clipboard; "
                            "you press Ctrl+V yourself. 'terminal': print to terminal only.")
    group.add_argument("--typer", default="auto", type=str,
                       help="Keystroke-injection backend. 'auto' (default) probes the "
                            "available backends. Explicit values: eitype, pynput, wtype, "
                            "ydotool — choose from those listed under Options → Keyboard "
                            "backend in the tray menu.")
    group.add_argument("-o", "--output-file",
                       help="Append the transcription to this file in addition to the "
                            "chosen --mode destination.")

    group = parser.add_argument_group("whisper options")
    group.add_argument("--duration", default=120, type=float, help="Max duration of the whisper recording (default %(default)s s)")
    group.add_argument("--silence", default=120, type=float, help="silence duration (default %(default)s s)")
    group.add_argument("--silence-db", default=-200, type=float, help="silence magnitude in decibel (default %(default)s db)")
    group.add_argument("-a", "--restart-after-silence", action="store_true", help="Restart the recording after a transcription triggered by a silence")
    group.add_argument("--download-folder-whisper", help="Folder to store Whisper models.")

    group = parser.add_argument_group("whisper api")
    group.add_argument("--api-key",
                        help="API key for the OpenAI backend (used by --backend openai).")

    group = parser.add_argument_group("App")
    group.add_argument("--vosk-models", nargs="*", help="vosk models available for the app mode", default=vosk_models)
    group.add_argument("--whisper-models", nargs="*", help="whisper models available for the app mode", default=whisper_models)

    parser.add_argument("--download-folder-vosk", help="Folder to store Vosk models.")

    return parser


# Commencer l'enregistrement
def _backend_name_of(session):
    """Robust accessor: works whether ``session`` is a RecordingSession (whose
    ``.backend`` is a transcriber) or a transcriber directly (whose ``.backend``
    is already a string name)."""
    obj = getattr(session, "backend", session)
    if isinstance(obj, str):
        return obj
    return getattr(obj, "backend", None)


def start_recording(micro, session, mode="keystroke", typer="auto",
                    output_file=None, callback=None, **greetings):
    """Drive a recording, dispatching the transcript to the destination implied
    by ``mode`` (the same three-way choice the tray exposes as Keyboard mode):

      - 'keystroke': land in the focused window. For streaming backends (vosk)
        each chunk is pasted live as it arrives; for batch backends the full
        text is pasted once at end-of-recording.
      - 'clipboard': copy to clipboard, user pastes manually.
      - 'terminal':  no clipboard, no keystroke — text only printed.
    """
    if mode not in ("keystroke", "clipboard", "terminal"):
        raise ValueError(f"Unknown mode {mode!r} (expected keystroke|clipboard|terminal)")

    backend_name = _backend_name_of(session)
    is_streaming = bool(getattr(BACKENDS.get(backend_name), "supports_streaming", False))
    do_clipboard = mode != "terminal"
    do_live_paste = (mode == "keystroke") and is_streaming
    do_paste_at_end = (mode == "keystroke") and not is_streaming

    if do_live_paste:
        from scribe.keyboard import paste_via_clipboard
        session.log("Live paste-per-chunk: each chunk lands in the focused window as it arrives.")

    if do_clipboard:
        import pyperclip
        session.log("The transcription will be copied to clipboard as it becomes available.")

    fulltext = ""

    for result in session.start_recording(micro, **greetings):

        if result.get('text'):
            clear_line()
            print(result.get('text'))
            chunk_text = result['text'] + " "
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
    extras = [opt for opt in ("restart_after_silence",) if getattr(o, opt, False)]
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
                transcriber_kwargs["prompt"] = False
            state.transcriber = get_transcriber(**transcriber_kwargs)
            state.session = None
        if state.session is None and not isinstance(state.transcriber, DummyTranscriber):
            state.session = RecordingSession(backend=state.transcriber)

        _print_main_status(state, o)

        if o.frontend == "terminal" and o.prompt:
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
                            **greetings)

        o.prompt = True
        o.backend = None
        o.model = None
        o.language = None

if __name__ == "__main__":
    main()