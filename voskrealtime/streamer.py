import os
from pathlib import Path
import json
import tomllib
import vosk
import argparse
from voskrealtime.audio import Microphone
from voskrealtime.util import clear_line, print_partial, download_model

LANGUAGE_MODELS_FOLDER = os.path.join(os.environ.get("HOME"),
                                      ".local/share/vosk/language-models")

with open(Path(__file__).parent / "models.toml", "rb") as f:
    language_config = tomllib.load(f)


# Load the Vosk recognizer
RECOGNIZER = {}

def get_recognizer(lang, samplerate=16000, data_folder=LANGUAGE_MODELS_FOLDER):
    if lang in RECOGNIZER:
        return RECOGNIZER[lang]

    model_path = os.path.join(data_folder, language_config[lang]["model"])
    if not os.path.exists(model_path):
        download_model(language_config[lang]["url"], data_folder)
        assert os.path.exists(model_path)

    model = vosk.Model(model_path)
    RECOGNIZER[lang] = vosk.KaldiRecognizer(model, samplerate)

    return RECOGNIZER[lang]


# Commencer l'enregistrement
def start_recording(micro, language, keyboard=False, latency=0, data_folder=LANGUAGE_MODELS_FOLDER, **kwargs):

    if keyboard:
        try:
            from voskrealtime.keyboard import type_text
        except ImportError:
            keyboard = False
            exit(1)

    rec = get_recognizer(language, micro.samplerate, data_folder=data_folder)

    with micro.open_stream():
        if language not in language_config:
            raise ValueError(language)
        meta = language_config[language]

        print(meta["start_message"])

        try:
            while True:
                while not micro.q.empty():
                    data = micro.q.get()
                    if rec.AcceptWaveform(data):
                        result = rec.Result()
                        result_dict = json.loads(result)
                        clear_line()
                        if len(result_dict['text']):
                            print(result_dict['text'])
                            if keyboard:
                                type_text(result_dict['text'] + " ", interval=latency) # Simulate typing

                    else:
                        partial_result = rec.PartialResult()
                        partial_result_dict = json.loads(partial_result)
                        print_partial(partial_result_dict['partial'])
                        continue

        except KeyboardInterrupt:
            pass

        print(meta["stop_message"])


def prompt_language():
    while True:
        print("""Press a key to start recording:""")
        for i, (lang, meta) in enumerate(language_config.items()):
            print(f"({i+1}) {lang}: {meta['language']}")
        res = input()
        if res.lower() in ("q", "quit"):
            exit(0)
        candidates = {str(i+1): lang for i, lang in enumerate(language_config)}
        candidates.update({lang.lower(): lang for lang in language_config})
        if res == "":
            res = "1"
        if res not in candidates:
            print("Invalid input.")
            continue
        return candidates[res]
        break



def main(args=None):

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-folder",
                        default=LANGUAGE_MODELS_FOLDER,)
    parser.add_argument("-l", "--language", choices=list(language_config), nargs="+",
                        help="Language to use (will skip the prompt). Default to letting you choose interactively.")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--custom-model")
    grp.add_argument("--custom-url")
    parser.add_argument("--keyboard", action="store_true")
    parser.add_argument("--latency", default=0, type=float, help="keyboard latency")
    o = parser.parse_args(args)

    # remove languages not specified (remove overhead when switching languages)
    if o.language:
        for lang in list(language_config):
            if lang not in o.language:
                language_config.pop(lang)

    if o.custom_model or o.custom_url:

        if o.custom_url:
            from urllib.parse import urlparse
            path = urlparse(o.custom_url).path
            basename = os.path.basename(path)
            o.custom_model = basename.replace(".zip", "")

        else:
            o.custom_url = f"https://alphacephei.com/vosk/models/{o.custom_model}.zip"

        language_config["custom"].update({
            "model": o.custom_model,
            "url": o.custom_url,
            })
    else:
        if "custom" in language_config:
            language_config.pop("custom")

    # Set up the microphone for recording
    micro = Microphone()

    while True:
        language = prompt_language()

        start_recording(micro, language, data_folder=o.data_folder,
                        samplerate=micro.samplerate, keyboard=o.keyboard, latency=o.latency)
        micro.q.queue.clear()

if __name__ == "__main__":
    main()