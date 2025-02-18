import os
import json
import time
from collections import deque
import numpy as np
from scribe.util import download_model
from scribe.audio import calculate_decibels

def is_silent(data, silence_thresh=-40):
    """
    Détermine si un segment audio est un silence en fonction du niveau de volume.
    """
    return calculate_decibels(data) < silence_thresh

VOSK_MODELS_FOLDER = os.path.join(os.environ.get("HOME"),
                                      ".local/share/vosk/language-models")


class AbstractTranscriber:
    backend = None
    def __init__(self, model, model_name=None, language=None, samplerate=16000, timeout=None, model_kwargs={},
                 silence_thresh=-40, silence_duration=2, restart_after_silence=False):
        self.model_name = model_name
        self.language = language
        self.model = model
        self.model_kwargs = model_kwargs
        self.samplerate = samplerate
        self.timeout = timeout
        self.silence_thresh = silence_thresh
        self.silence_duration = silence_duration
        self.restart_after_silence = restart_after_silence
        self.reset()

    def get_elapsed(self):
        return time.time() - self.start_time

    def is_overtime(self):
        return self.timeout is not None and time.time() - self.start_time > self.timeout

    def transcribe_realtime_audio(self, audio_bytes=b""):
        self.audio_buffer += audio_bytes
        return {"partial": f"{len(self.audio_buffer)} bytes received (duration: {self.get_elapsed()} seconds)"}

    def transcribe_audio(self, audio_data):
        raise NotImplementedError()

    def reset(self):
        self.audio_buffer = b''
        self.start_time = time.time()
        self.last_sound_time = time.time()

    def start_recording(self, microphone,
                        start_message="Recording... Press Ctrl+C to stop.",
                        stop_message="Stopped recording."):

        self.reset()

        with microphone.open_stream():
            print(start_message)

            try:
                while True:
                    while not microphone.q.empty():
                        data = microphone.q.get()

                        # Vérifier si le segment est un silence
                        if is_silent(data, self.silence_thresh):
                            silence_duration = time.time() - self.last_sound_time

                            if self.silence_duration is not None and silence_duration >= self.silence_duration and len(self.audio_buffer) > 0:
                                if self.restart_after_silence:
                                    result = self.finalize()
                                    microphone.q.queue.clear()
                                    self.reset()
                                    yield result
                                else:
                                    raise KeyboardInterrupt("Silence detected: {:.2f} seconds".format(silence_duration))

                        else:
                            self.last_sound_time = time.time()

                        yield self.transcribe_realtime_audio(data)

                        if self.is_overtime():
                            raise KeyboardInterrupt("Overtime: {:.2f} seconds".format(self.get_elapsed()))

            except KeyboardInterrupt:
                pass

            finally:
                result = self.finalize()
                microphone.q.queue.clear()
                yield result

            print(stop_message)


def get_vosk_model(model, data_folder=None, url=None):
    """Load the Vosk recognizer"""
    import vosk
    if data_folder is None:
        data_folder = VOSK_MODELS_FOLDER
    model_path = os.path.join(data_folder, model)
    if not os.path.exists(model_path):
        if url is None:
            url = f"https://alphacephei.com/vosk/models/{model}.zip"
        download_model(url, data_folder)
        assert os.path.exists(model_path)

    return vosk.Model(model_path)


def get_vosk_recognizer(model, samplerate=16000):
    import vosk
    return vosk.KaldiRecognizer(model, samplerate)


class VoskTranscriber(AbstractTranscriber):
    backend = "vosk"

    def __init__(self, model_name, model=None, model_kwargs={}, **kwargs):
        if model is None:
            model = get_vosk_model(model_name, **model_kwargs)
        super().__init__(model, model_name, model_kwargs=model_kwargs, **kwargs)
        self.recognizer = get_vosk_recognizer(model, self.samplerate)

    def transcribe_realtime_audio(self, audio_bytes=b""):
        self.audio_buffer += audio_bytes
        final = self.recognizer.AcceptWaveform(audio_bytes)
        if final:
            result = self.recognizer.Result()
        else:
            result = self.recognizer.PartialResult()
        result_dict = json.loads(result)

        if final:
            pass
        else:
            assert not final
            if "text" in result_dict:
                del result_dict["text"]
        return result_dict

    def transcribe_audio(self, audio_data=b""):
        results = self.transcribe_realtime_audio(audio_data)
        if not results.get("text") and "partial" in results:
            results["text"] = results.pop("partial", "")
        return results


    def finalize(self):
        return self.transcribe_audio(b"")

    def reset(self):
        super().reset()
        self.recognizer = get_vosk_recognizer(self.model, self.samplerate)


class WhisperTranscriber(AbstractTranscriber):
    backend = "whisper"

    def __init__(self, model_name, language=None, model=None, model_kwargs={}, **kwargs):
        import whisper
        if model is None:
            model = whisper.load_model(model_name)
        super().__init__(model, model_name, language, model_kwargs=model_kwargs, **kwargs)

    def transcribe_audio(self, audio_bytes):
        print("Transcribing...")
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).flatten().astype(np.float32) / 32768.0
        return self.model.transcribe(audio_array, fp16=False, language=self.language)

    def finalize(self):
        if len(self.audio_buffer) == 0:
            return {"text": ""}
        result = self.transcribe_audio(self.audio_buffer)
        self.audio_buffer = b''
        return result