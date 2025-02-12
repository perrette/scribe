import os
from pathlib import Path
import json
import vosk
import argparse
from voskrealtime.audio import Microphone
from voskrealtime.util import clear_line, print_partial

language_config_default = {
    "en" : {
        "model": "vosk-model-en-us-0.42-gigaspeech",
        "language": "English (US)",
        "start message": "Listening... Press Ctrl+C to stop.",
        "stop message": "Recording stopped."
    },
    "fr" : {
        "model": "vosk-model-fr-0.22",
        "language": "French",
        "start message": "En écoute... Appuyez sur Ctrl+C pour arrêter.",
        "stop message": "Écoute arrêtée."
    }
}


def main(args=None):

    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--language", nargs="+", choices=list(language_config_default),
                        default=["en"])
    o = parser.parse_args(args)

    DATA = Path(f"/home/perrette/.local/share/vosk/language-models")

    language_config = {lang: language_config_default[lang] for lang in o.language}

    # Set up the microphone for recording
    micro = Microphone()

    # Chargez le modèle Vosk
    recognizers = {}
    for lang in o.language:
        model_path = str(DATA/language_config[lang]["model"])
        if not os.path.exists(model_path):
            print(f"Please download the model for {lang} from https://alphacephei.com/vosk/models and unpack as {model_path}")
            raise Exception(f"Vosk model not found for {lang}!")

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