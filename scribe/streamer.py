from pathlib import Path
import tomllib
import argparse
from scribe.audio import Microphone
from scribe.util import print_partial, clear_line, prompt_choices, check_dependencies, ansi_link, colored
from scribe.models import VoskTranscriber, WhisperTranscriber

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
        backend = choices[0]

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
                                        model_kwargs={"data_folder": o.data_folder})
        except Exception as error:
            print(error)
            print(f"Failed to (down)load model {model}.")
            exit(1)

    elif backend == "whisper":
        transcriber = WhisperTranscriber(model_name=model, language=o.language, samplerate=o.samplerate, timeout=o.duration, silence_duration=o.silence)

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

    parser.add_argument("--samplerate", default=16000, type=int, help=argparse.SUPPRESS)
    parser.add_argument("--keyboard", action="store_true")
    parser.add_argument("--no-clipboard", dest="clipboard", action="store_false")
    parser.add_argument("--latency", default=0, type=float, help="keyboard latency")

    group = parser.add_argument_group("whisper options")
    group.add_argument("--duration", default=120, type=int, help="Max duration of the whisper recording (default %(default)ss)")
    group.add_argument("--silence", default=2, type=float, help="silence duration that prompt transcription (whisper) (default %(default)ss)")
    group.add_argument("--restart-after-silence", action="store_true", help="Restart the recording after a transcription triggered by a silence")

    parser.add_argument("--data-folder", help="Folder to store Vosk models.")

    return parser


# Commencer l'enregistrement
def start_recording(micro, transcriber, clipboard=True, keyboard=False, latency=0):

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

    greetings = { k: v for k, v in language_config["_meta"].get(transcriber.language, {}).items()
                if v is not None and k.startswith(("start", "stop"))
    }

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



def main(args=None):

    parser = get_parser()
    o = parser.parse_args(args)


    # Set up the microphone for recording
    micro = Microphone(samplerate=o.samplerate)

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
            print(f"[k] toggle keyboard [{toggle[o.keyboard]}] -> [{toggle[not o.keyboard]}]")
            print(f"[c] toggle clipboard [{toggle[o.clipboard]}] -> [{toggle[not o.clipboard]}]")
            if transcriber.backend == "whisper":
                print(f"[t] change duration (currently {transcriber.timeout}s)")
                print(f"[b] change silence duration (currently {transcriber.silence_duration}s)")
                print(f"[a] toggle auto-restart after silence [{toggle[o.restart_after_silence]}] -> [{toggle[not o.restart_after_silence]}]")
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

        start_recording(micro, transcriber, clipboard=o.clipboard, keyboard=o.keyboard, latency=o.latency)

        # if we arrived so far, that means we pressed Ctrl + C anyway, and need Enter to move on.
        # So we leave the wider range of options to change the model.
        o.prompt = True
        o.backend = None
        o.model = None
        o.language = None

if __name__ == "__main__":
    main()