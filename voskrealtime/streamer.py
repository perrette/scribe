from pathlib import Path
import tomllib
import argparse
from voskrealtime.audio import Microphone
from voskrealtime.util import print_partial, clear_line
from voskrealtime.models import VoskTranscriber, WhisperTranscriber

with open(Path(__file__).parent / "models.toml", "rb") as f:
    language_config_default = tomllib.load(f)

language_config = language_config_default.copy()


# Commencer l'enregistrement
def start_recording(micro, transcriber, keyboard=False, latency=0):

    if keyboard:
        try:
            from voskrealtime.keyboard import type_text
        except ImportError:
            keyboard = False
            exit(1)

    greetings = { k: v for k, v in language_config["_meta"].get(transcriber.language, {}).items()
                if v is not None
    }

    for result in transcriber.start_recording(micro, **greetings):

        if result.get('text'):
            clear_line()
            print(result.get('text'))
            if keyboard:
                type_text(result['text'] + " ", interval=latency) # Simulate typing
        else:
            print_partial(result.get('partial', ''))


def main(args=None):

    parser = argparse.ArgumentParser()
    parser.add_argument("--model",
                        help="""For vosk, any model from https://alphacephei.com/vosk/models,
                        e.g. 'vosk-model-small-en-us-0.15'.
                        For whisper, see https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages""")

    parser.add_argument("--backend", choices=["vosk", "whisper"], default="vosk",
                        help="Choose the backend to use for speech recognition.")

    parser.add_argument("-l", "--language", choices=list(language_config["vosk"]),
                        help="An alias for preselected models.")

    parser.add_argument("--samplerate", default=16000, type=int)
    parser.add_argument("--keyboard", action="store_true")
    parser.add_argument("--latency", default=0, type=float, help="keyboard latency")

    parser.add_argument("--data-folder", help="Folder to store Vosk models.")

    o = parser.parse_args(args)

    if not o.model and not o.language:
        if o.backend == "whisper":
            o.model = "turbo"

        elif o.backend == "vosk":
            print(f"Please specify a model `--model` or language `-l, --language` for backend {o.backend}).")
            exit(1)

        else:
            raise ValueError(f"Unknown backend: {o.backend}")

    if o.language and not o.model:
        if o.backend == "vosk":
            try:
                meta = language_config[o.backend][o.language]
            except KeyError:
                    print(f"Language '{o.language}' not found for backend '{o.backend}'.")
                    print(f"Available languages for backend {o.backend}: ", list(language_config.get(o.backend, {})))
                    exit(1)
            o.model = meta["model"]
        elif o.backend == "whisper":
            o.model = "turbo"
            if o.language == "en":
                o.model += ".en"
        else:
            raise ValueError(f"Unknown backend: {o.backend}")


    if o.backend == "vosk":
        transcriber = VoskTranscriber(model_name=o.model,
                                      language=o.language,
                                      samplerate=o.samplerate,
                                      model_kwargs={"data_folder": o.data_folder})

    elif o.backend == "whisper":
        transcriber = WhisperTranscriber(model_name=o.model, language=o.language, samplerate=o.samplerate)

    else:
        raise ValueError(f"Unknown backend: {o.backend}")

    # Set up the microphone for recording
    micro = Microphone(samplerate=o.samplerate)

    while True:
        input(f"Press any key to start recording [model: {transcriber.model_name}]")
        start_recording(micro, transcriber, keyboard=o.keyboard, latency=o.latency)

if __name__ == "__main__":
    main()