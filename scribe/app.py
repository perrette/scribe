from pathlib import Path
import tomllib
import argparse
from scribe.audio import Microphone
from scribe.util import print_partial, clear_line, prompt_choices, check_dependencies, ansi_link, colored
from scribe.models import VoskTranscriber, WhisperTranscriber, StopRecording

with open(Path(__file__).parent / "models.toml", "rb") as f:
    language_config_default = tomllib.load(f)

language_config = language_config_default.copy()


def get_default_backend():
    try:
        import vosk
        return "vosk"
    except ImportError:
        try:
            import whisper
            return "whisper"
        except ImportError:
            raise ImportError("Please install either vosk or whisper to use this script.")

BACKENDS = ["whisper", "vosk"]
UNAVAILABLE_BACKENDS = []


def pick_specialist_model(model, language, backend):
    """ choose a specialist version of a model if language is specified (whisper)"""

    if backend == "whisper" and language and language.lower() in ["en", "english"]:
        available_models_en = ["tiny.en", "base.en", "small.en", "medium.en", "large", "turbo"]
        if model + ".en" in available_models_en:
            model += ".en"

    return model


def get_transcriber(o, prompt=True):

    if o.backend:
        checked_backend = check_dependencies(o.backend)
        if not checked_backend:
            print(f"Backend {o.backend} is not available.")
            exit(1)
        backend = o.backend

    elif not prompt:
        backend = BACKENDS[0]

    else:
        checked_backend = False
        while not checked_backend:
            backend = prompt_choices(BACKENDS, o.backend, "backend", UNAVAILABLE_BACKENDS)
            # raise an error if the user has explicitly selected a backend that is not available
            checked_backend = check_dependencies(backend, raise_error=backend==o.backend)
            if not checked_backend:
                print(f"Backend {o.backend} is not available.")
                UNAVAILABLE_BACKENDS.append(backend)

    print(f"Selected backend: {backend}")

    if o.model:
        model = pick_specialist_model(o.model, o.language, backend)

    else:

        if backend == "vosk":
            available_languages = list(language_config[backend])
            if o.language:
                if o.language not in available_languages:
                    print(f"Language '{o.language}' is not pre-defined (yet) for backend '{backend}'.")
                    print(f"Yet it may actually exist.")
                    print(f"Please choose the model explictly from {ansi_link('https://alphacephei.com/vosk/models')}.")
                    print(f"Or pick one of the pre-defined languages: ", " ".join(available_languages))
                    exit(1)
                choices = [language_config[backend][o.language]["model"]]
                default_model = choices[0]

            else:
                available_models = [language_config[backend][lang]["model"] for lang in available_languages]
                choices = list(zip(available_models, available_languages)) + [f" * [Any model from {ansi_link('https://alphacephei.com/vosk/models')}]"]
                default_model = choices[0]

            print(f"For information about vosk models see: {ansi_link('https://alphacephei.com/vosk/models')}")
            if prompt:
                model = prompt_choices(choices, default=default_model, label="model")
            else:
                model = default_model

        elif backend == "whisper":

            models = ["tiny", "base", "small", "medium", "large", "turbo"]
            english_models = ["tiny.en", "base.en", "small.en", "medium.en"]
            default_model = "small"

            print("Some models have a specialized English version (.en) which will be selected as default is `-l en` was requested, but can also be requested explicitly below (option not listed). See [documentation](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages).")
            if prompt:
                model = prompt_choices(models, default=default_model, label="model",
                                        hidden_models=english_models)
            else:
                model = default_model

            model = pick_specialist_model(model, o.language, backend)

    print(f"Selected model: {model}")

    if backend == "vosk":
        try:
            transcriber = VoskTranscriber(model_name=model,
                                        language=o.language,
                                        samplerate=o.samplerate,
                                        timeout=None, # vosk keeps going (no timeout)
                                        silence_duration=None, # vosk handles silences internally
                                        model_kwargs={"download_root": o.download_folder_vosk})
        except Exception as error:
            print(error)
            print(f"Failed to (down)load model {model}.")
            exit(1)

    elif backend == "whisper":
        transcriber = WhisperTranscriber(model_name=model, language=o.language, samplerate=o.samplerate,
                                         timeout=o.duration, silence_duration=o.silence, restart_after_silence=o.restart_after_silence,
                                         model_kwargs={"download_root": o.download_folder_whisper})

    else:
        raise ValueError(f"Unknown backend: {backend}")

    return transcriber

def get_parser():

    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=BACKENDS,
                        help="Choose the backend to use for speech recognition (will be prompted otherwise).")

    parser.add_argument("--model",
                        help="""For vosk, any model from https://alphacephei.com/vosk/models,
                        e.g. 'vosk-model-small-en-us-0.15'.
                        For whisper, see https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages""")

    parser.add_argument("-l", "--language", choices=list(language_config["vosk"]),
                        help="An alias for preselected models when using the vosk backend, or 'en' for the English version of whisper models.")

    parser.add_argument("--no-prompt", action="store_false", dest="prompt", help="Disable prompts for backend and model selection and jump to recording")
    parser.add_argument("--app", action="store_true", help="Start in app mode (relies on pystray)")

    parser.add_argument("--samplerate", default=16000, type=int, help=argparse.SUPPRESS)
    parser.add_argument("--microphone-device", help="The device index of the microphone to use.", type=int)
    parser.add_argument("--keyboard", action="store_true")
    parser.add_argument("--no-clipboard", dest="clipboard", action="store_false")
    parser.add_argument("--latency", default=0, type=float, help="keyboard latency")

    group = parser.add_argument_group("whisper options")
    group.add_argument("--duration", default=120, type=int, help="Max duration of the whisper recording (default %(default)ss)")
    group.add_argument("--silence", default=2, type=float, help="silence duration that prompt transcription (whisper) (default %(default)ss)")
    group.add_argument("--restart-after-silence", action="store_true", help="Restart the recording after a transcription triggered by a silence")

    parser.add_argument("--download-folder-vosk", help="Folder to store Vosk models.")
    parser.add_argument("--download-folder-whisper", help="Folder to store Whisper models.")

    return parser


# Commencer l'enregistrement
def start_recording(micro, transcriber, clipboard=True, keyboard=False, latency=0, **greetings):

    if keyboard:
        try:
            from scribe.keyboard import type_text
        except ImportError:
            keyboard = False
            print("Keyboard simulation is not available.")
            return

        print("\nChange focus to target app during transcription.")


    if clipboard:
        try:
            import pyperclip
        except ImportError:
            clipboard = False
            print("Clipboard simulation is not available.")
            return

        print("\nThe full transcription will be copied to clipboard as it becomes available.")


    fulltext = ""

    for result in transcriber.start_recording(micro, **greetings):

        if result.get('text'):
            clear_line()
            print(result.get('text'))
            if keyboard:
                type_text(result['text'] + " ", interval=latency) # Simulate typing

            if clipboard:
                fulltext += result['text'] + " "
                pyperclip.copy(fulltext)

        else:
            print_partial(result.get('partial', ''))

    if clipboard:
        print("Copied to clipboard.")


def interrupt_app_thread(icon):
    """Thanks Le Chat for this solution: https://stackoverflow.com/a/325528/2192272
    """
    import ctypes
    thread = icon._recording_thread
    # Raise an exception in the thread using ctypes
    thread_id = thread.ident
    if thread_id is not None:
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(thread_id),
            ctypes.py_object(StopRecording)
        )
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            print("Failure to raise exception in thread")


def create_app(micro, transcriber, **kwargs):
    import pystray
    from pystray import Menu as pystrayMenu, MenuItem as Item
    from PIL import Image
    import PIL.ImageOps

    import scribe_data
    import threading

    # Load an image from a file
    image = Image.open(Path(scribe_data.__file__).parent / "share" / "icon.jpg")

    def callback_quit(icon, item):
        icon.visible = False
        ## Here we need to stop the recording thread
        callback_stop_recording(icon, item)
        icon.stop()

    def callback_stop_recording(icon, item):
        ## Here we need to stop the recording thread
        interrupt_app_thread(icon)
        icon._recording_thread.join()

    def callback_record(icon, item):
        icon._recording_thread = threading.Thread(target=start_recording, args=(micro, transcriber), kwargs=kwargs)
        icon._recording_thread.start()

    def is_recording(item):
        return hasattr(icon, "_recording_thread") and icon._recording_thread.is_alive()

    def is_not_recording(item):
        return not is_recording(item)


    # Create a menu
    menu = pystrayMenu(
        # Item('Record', callback_record),
        Item("Record", callback_record, visible=is_not_recording),
        Item("Stop", callback_stop_recording, visible=is_recording),
        Item('Quit', callback_quit),
    )

    # Create the system tray icon
    icon = pystray.Icon('scribe', image, "scribe", menu)

    return icon


def main(args=None):

    parser = get_parser()
    o = parser.parse_args(args)


    # Set up the microphone for recording
    micro = Microphone(samplerate=o.samplerate, device=o.microphone_device)

    transcriber = None

    toggle = {True: "On", False: "Off"}

    while True:
        if transcriber is None:
            transcriber = get_transcriber(o, prompt=o.prompt)
        print(f">>> Model {transcriber.model_name} from {transcriber.backend} selected. Keyboard [{'on' if o.keyboard else 'off'}]. Clipboard [{'on' if o.clipboard else 'off'}] <<<")
        if o.prompt:
            print(f"Choose any of the following actions:")
            print(f"[q] quit")
            print(f"[e] change model")
            print(f"[x] toggle app [{toggle[o.app]}] -> [{toggle[not o.app]}]")
            print(f"[k] toggle keyboard [{toggle[o.keyboard]}] -> [{toggle[not o.keyboard]}]")
            print(f"[c] toggle clipboard [{toggle[o.clipboard]}] -> [{toggle[not o.clipboard]}]")
            if transcriber.backend == "whisper":
                print(f"[t] change duration (currently {transcriber.timeout}s)")
                print(f"[b] change silence duration (currently {transcriber.silence_duration}s)")
                print(f"[a] toggle auto-restart after silence [{toggle[transcriber.restart_after_silence]}] -> [{toggle[not transcriber.restart_after_silence]}]")
            print(colored(f"Press [Enter] or any other key to start recording.", "BOLD"))

            key = input()
            if key == "q":
                exit(0)
            if key == "e":
                transcriber = None
                continue
            if key == "k":
                o.keyboard = not o.keyboard
                continue
            if key == "c":
                o.clipboard = not o.clipboard
                continue
            if key == "x":
                o.app = not o.app
                continue
            if key == "a":
                transcriber.restart_after_silence = not transcriber.restart_after_silence
                continue
            if key == "t":
                ans = input(f"Enter new duration in seconds (current: {transcriber.timeout}): ")
                try:
                    o.duration = transcriber.timeout = int(ans)
                except:
                    print("Invalid duration. Must be an integer.")
                continue
            if key == "b":
                ans = input(f"Enter new silence break duration in seconds (current: {transcriber.silence_duration}): ")
                try:
                    o.silence = transcriber.silence_duration = int(ans)
                except:
                    print("Invalid duration. Must be an integer.")
                continue

        if o.app:
            greetings = dict(
                start_message = "Listening... Use the try icon menu to stop.",
            )
            app = create_app(micro, transcriber, clipboard=o.clipboard, keyboard=o.keyboard, latency=o.latency, **greetings)
            print("Starting app...")
            app.run()
        else:
            greetings = dict(
                start_message = "Listening... Press Ctrl+C to stop.",
            )
            start_recording(micro, transcriber, clipboard=o.clipboard, keyboard=o.keyboard, latency=o.latency, **greetings)

        # if we arrived so far, that means we pressed Ctrl + C anyway, and need Enter to move on.
        # So we leave the wider range of options to change the model.
        o.prompt = True
        o.backend = None
        o.model = None
        o.language = None

if __name__ == "__main__":
    main()