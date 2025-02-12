import os
from pathlib import Path
import wave
import json
import shutil
import sounddevice as sd
import vosk
import queue

import sounddevice as sd
import numpy as np

model_en = "vosk-model-en-us-0.42-gigaspeech"
model_fr = "vosk-model-fr-0.22"

# Set up the microphone for recording
samplerate = 16000  # Vosk models typically use a 16kHz sample rate
duration = 5  # seconds
channels = 1  # Mono audio
device = None  # Default device
# device = 8

# Set the minimum audio duration in seconds (for example, 2 seconds)
MIN_AUDIO_DURATION = 5  # In seconds
MIN_AUDIO_SAMPLES = MIN_AUDIO_DURATION * samplerate  # Minimum samples for the duration


device_info = sd.query_devices(device, 'input')
print(device_info)

# # Record audio
# print("Recording...")
# audio_data = sd.rec(int(samplerate * duration), samplerate=samplerate, channels=channels, device=device)
# sd.wait()  # Wait until recording is finished

# # Play the recorded audio back
# print("Playing back...")
# sd.play(audio_data, samplerate=samplerate)
# sd.wait()
# print("Finished playback.")


# Set up the Vosk model
HOME = "/home/perrette"
DATA = Path(f"{HOME}/.local/share/vosk/language-models")


# if not os.path.exists(model_path):
#     print(f"Please download the model from https://alphacephei.com/vosk/models and unpack as {model_path}")
#     raise Exception("Vosk model not found!")

# Chargez le modèle Vosk
model_fr = vosk.Model(str(DATA/model_fr))
model_en = vosk.Model(str(DATA/model_en))

# Queue to hold audio data
q = queue.Queue()

# Fonction callback pour traiter les morceaux audio
def callback(indata, frames, time, status):
    if status:
        print(status)
    q.put(bytes(indata))
    # if frames > 1000:  # Ajustez cette valeur pour essayer différents morceaux de taille
    #     rec.AcceptWaveform(bytes(indata))    

# Initialiser le reconnaisseur Vosk
rec_fr = vosk.KaldiRecognizer(model_fr, samplerate)
rec_en = vosk.KaldiRecognizer(model_en, samplerate)
rec = rec_fr

# Function to clear the terminal line
def clear_line():
    # Get terminal width
    terminal_width = shutil.get_terminal_size().columns
    print("\r" + " " * terminal_width, end="")  # Clear the line
    print("\r", end="")  # Return cursor to the beginning of the line


def print_partial(msg):
    # Get terminal width
    terminal_width = shutil.get_terminal_size().columns
    start = max(0, len(msg) + 7 - terminal_width)
    print(f"\r[...] {msg[start:]}", end="")

# Commencer l'enregistrement
def start_recording(language="fr"):

    with sd.InputStream(samplerate=samplerate, device=None, channels=channels, callback=callback, dtype='int16'):
        if language == "fr":
            print("En écoute... Appuyez sur Ctrl+C pour arrêter.")
            rec = rec_fr
        elif language == "en":
            print("Listening... Press Ctrl+C to stop.")
            rec = rec_en
        else:
            raise ValueError(language)

        try:
            while True:
                # Traiter les morceaux audio
                while not q.empty():
                    data = q.get()
                    # print("Donnée audio reçue...")
                    if rec.AcceptWaveform(data):
                        result = rec.Result()
                        result_dict = json.loads(result)
                        # print(f"Transcription: {result_dict['text']}")
                        clear_line()
                        print(result_dict['text'])

                    else:
                        # Afficher le résultat brut pour comprendre pourquoi il est rejeté
                        # print("Résultat brut non accepté par Vosk:")
                        partial_result = rec.PartialResult()
                        partial_result_dict = json.loads(partial_result)                   
                        print_partial(partial_result_dict['partial'])
                        continue

        except KeyboardInterrupt:
            pass
            print("Écoute arrêtée.")


while True:
    while True:
        print("""Press a key to start recording:
    1: FR
    2: EN""")
        res = input()
        if res.lower() in ("1", "fr"):
            language = "fr"
            break
        elif res.lower() in ("2", "en"):
            language = "en"
            break

    start_recording(language)
    q.queue.clear()