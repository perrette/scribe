import os
from pathlib import Path
import json
import vosk
import argparse
from voskrealtime.audio import Microphone
from voskrealtime.util import clear_line, print_partial

LANGUAGE_MODELS_FOLDER = os.path.join(os.environ.get("HOME"),
                                      ".local/share/vosk/language-models")

language_config_default = {
    "en" : {
        "model": "vosk-model-en-us-0.42-gigaspeech",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.42-gigaspeech.zip",
        "language": "English (US)",
        "start message": "Listening... Press Ctrl+C to stop.",
        "stop message": "Recording stopped."
    },
    "fr" : {
        "model": "vosk-model-fr-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-fr-0.22.zip",
        "language": "French",
        "start message": "En écoute... Appuyez sur Ctrl+C pour arrêter.",
        "stop message": "Écoute arrêtée."
    },
    "de" : {
        "model": "vosk-model-de-tuda-0.6-900k",
        "url": "https://alphacephei.com/vosk/models/vosk-model-de-tuda-0.6-900k.zip",
        "language": "German",
        "start message": "Hören... Drücken Sie Strg+C, um zu stoppen.",
        "stop message": "Aufnahme gestoppt."
    },
    "it" : {
        "model": "vosk-model-it-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-it-0.22.zip",
        "language": "Italian",
        "start message": "In ascolto... Premere Ctrl+C per interrompere.",
        "stop message": "Registrazione interrotta."
    },
    "custom" : {
        "start message": "Listening... Press Ctrl+C to stop.",
        "stop message": "Recording stopped.",
        "language": "custom",
    },
}

def download_model(url, data_folder):
    import requests
    import zipfile
    import io

    os.makedirs(data_folder, exist_ok=True)

    print(f"Downloading model from {url}...")
    r = requests.get(url)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    z.extractall(data_folder)
    print(f"Model downloaded and unpacked to {data_folder}")

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

            print(meta["start message"])
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

            print(meta["stop message"])

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