import os
import json
import numpy as np
from scribe.util import download_model

VOSK_MODELS_FOLDER = os.path.join(os.environ.get("HOME"),
                                      ".local/share/vosk/language-models")


class AbstractTranscriber:
    backend = None
    def __init__(self, model, model_name=None, language=None, samplerate=16000, model_kwargs={}):
        self.model_name = model_name
        self.language = language
        self.model = model
        self.model_kwargs = model_kwargs
        self.samplerate = samplerate

    def transcribe_audio(self, audio_data):
        raise NotImplementedError()

    def transcribe_realtime_audio(self, audio_data):
        raise NotImplementedError()

    def start_recording(self, microphone,
                        start_message="Recording... Press Ctrl+C to stop.",
                        stop_message="Stopped recording."):

        with microphone.open_stream():
            print(start_message)

            try:
                while True:
                    while not microphone.q.empty():
                        data = microphone.q.get()
                        yield self.transcribe_realtime_audio(data)

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

    def transcribe_realtime_audio(self, audio_bytes=b"", finalize=False):
        final = self.recognizer.AcceptWaveform(audio_bytes)
        if final:
            result = self.recognizer.Result()
        else:
            result = self.recognizer.PartialResult()
        result_dict = json.loads(result)

        if final:
            pass
        elif finalize:
            result_dict["text"] = result_dict.pop("partial", "")
        else:
            assert not final
            if "text" in result_dict:
                del result_dict["text"]
        return result_dict

    def transcribe_audio(self, audio_data=None):
        return self.transcribe_realtime_audio(audio_data, finalize=True)

    def finalize(self):
        return self.transcribe_audio(b"")


class WhisperTranscriber(AbstractTranscriber):
    backend = "whisper"

    def __init__(self, model_name, language=None, model=None, model_kwargs={}, **kwargs):
        import whisper
        if model is None:
            model = whisper.load_model(model_name)
        super().__init__(model, model_name, language, model_kwargs=model_kwargs, **kwargs)
        self.audio_buffer = b''

    def transcribe_realtime_audio(self, audio_bytes=b"", max_duration=60):
        self.audio_buffer += audio_bytes

        one_second = self.samplerate * 2 # 16-bit audio, 1 channel  ~ 32000 bytes
        if len(self.audio_buffer) < max_duration * one_second:
            return {"partial": f"{len(self.audio_buffer)} bytes received (duration: {len(self.audio_buffer) / one_second:.2f} seconds)"}

        else:
            return self.finalize()

    def transcribe_audio(self, audio_bytes):
        print("\nTranscribing...")
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).flatten().astype(np.float32) / 32768.0
        return self.model.transcribe(audio_array, fp16=False, language=self.language)

    def finalize(self):
        if len(self.audio_buffer) == 0:
            return {"text": ""}
        result = self.transcribe_audio(self.audio_buffer)
        self.audio_buffer = b''
        return result
