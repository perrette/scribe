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
    language_config_default = tomllib.load(f)

def main(args=None):

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-folder",
                        default=LANGUAGE_MODELS_FOLDER,)
    parser.add_argument("-l", "--language", nargs="+", choices=list(language_config_default),
                        default=["en"])
    parser.add_argument("--custom-model")
    parser.add_argument("--custom-url")
    o = parser.parse_args(args)

    language_config = {lang: language_config_default[lang] for lang in o.language}

    if o.custom_model or o.custom_url:

        if not o.custom_model:
            from urllib.parse import urlparse
            path = urlparse(o.custom_url).path
            basename = os.path.basename(path)
            o.custom_model = basename.replace(".zip", "")

        elif not o.custom_url:
            o.custom_url = f"https://alphacephei.com/vosk/models/{o.custom_model}.zip"

        language_config["custom"].update({
            "model": o.custom_model,
            "url": o.custom_url,
            })

    # Set up the microphone for recording
    micro = Microphone()

    # Chargez le modèle Vosk
    recognizers = {}
    for lang in o.language:
        model_path = os.path.join(o.data_folder, language_config[lang]["model"])
        if not os.path.exists(model_path):
            download_model(language_config[lang]["url"], o.data_folder)
            assert os.path.exists(model_path)

        model = vosk.Model(model_path)
        recognizers[lang] = vosk.KaldiRecognizer(model, micro.samplerate)

    # Commencer l'enregistrement
    def start_recording(language="fr"):

        with micro.open_stream():
            if language not in language_config:
                raise ValueError(language)
            meta = language_config[language]

            print(meta["start_message"])
            rec = recognizers[language]

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

                        else:
                            partial_result = rec.PartialResult()
                            partial_result_dict = json.loads(partial_result)
                            print_partial(partial_result_dict['partial'])
                            continue

            except KeyboardInterrupt:
                pass

            print(meta["stop_message"])

    while True:
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
            language = candidates[res]
            break

        start_recording(language)
        micro.q.queue.clear()


if __name__ == "__main__":
    main()