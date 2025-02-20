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

HOME = os.environ.get('HOME', os.path.expanduser('~'))
XDG_CACHE_HOME = os.environ.get('XDG_CACHE_HOME', os.path.join(HOME, '.cache'))
VOSK_MODELS_FOLDER = os.path.join(XDG_CACHE_HOME, "vosk")

class StopRecording(Exception):
    pass

class AbstractTranscriber:
    backend = None
    def __init__(self, model, model_name=None, language=None, samplerate=16000, timeout=None, model_kwargs={},
                 silence_thresh=-40, silence_duration=2, restart_after_silence=False, logger=None):
        self.model_name = model_name
        self.language = language
        self.model = model
        self.model_kwargs = model_kwargs
        self.samplerate = samplerate
        self.timeout = timeout
        self.silence_thresh = silence_thresh
        self.silence_duration = silence_duration
        self.restart_after_silence = restart_after_silence
        self.recording = False
        self.busy = False
        self.waiting = False
        self.interrupt = False
        if logger is None:
            import logging
            logging.basicConfig(level=logging.INFO)
            logger = logging.getLogger("scribe")
        self.logger = logger
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

    def log(self, text):
        if text.startswith("\n"):
            print("")
            text = text[1:]
        if self.logger:
            self.logger.info(text)
        else:
            print(f"[{text}]")

    def start_recording(self, microphone,
                        start_message="Recording... Press Ctrl+C to stop.",
                        stop_message="Exit."):

        self.reset()
        self.interrupt = False
        self.recording = True
        self.waiting = True
        self.busy = True
        if self.silence_duration is not None:
            self.last_sound_time = time.time() - self.silence_duration
        else:
            self.last_sound_time = time.time()
        previous_waiting = self.waiting

        try:

            with microphone.open_stream():
                self.log(start_message)

                while not self.interrupt:
                    while not microphone.q.empty():
                        data = microphone.q.get()

                        # Vérifier si le segment est un silence
                        if is_silent(data, self.silence_thresh):
                            silence_duration = time.time() - self.last_sound_time

                            previous_waiting = self.waiting
                            self.waiting = self.silence_duration is not None and silence_duration >= self.silence_duration

                            if self.waiting and len(self.audio_buffer) > 0:
                                if self.restart_after_silence:
                                    self.recording = False # for the system tray icon
                                    result = self.finalize()
                                    microphone.q.queue.clear()
                                    self.reset()
                                    yield result
                                    self.recording = True # for the system tray icon
                                else:
                                    raise StopRecording("Silence detected: {:.2f} seconds".format(silence_duration))

                        else:
                            self.last_sound_time = time.time()
                            self.waiting = False

                        # don't accumulate very long silences
                        if not self.waiting:
                            yield self.transcribe_realtime_audio(data)

                        else:
                            if not previous_waiting:
                                self.log("Silence detected...waiting for more audio")

                        if self.is_overtime():
                            raise StopRecording("Overtime: {:.2f} seconds".format(self.get_elapsed()))

                    time.sleep(0.1) # avoid overheating

        except (KeyboardInterrupt, StopRecording):
            pass

        finally:
            self.waiting = False
            self.recording = False
            result = self.finalize()
            microphone.q.queue.clear()
            self.busy = False
            yield result

        self.log(stop_message)


def get_vosk_model(model, download_root=None, url=None):
    """Load the Vosk recognizer"""
    import vosk
    vosk.SetLogLevel(-1)
    if download_root is None:
        download_root = VOSK_MODELS_FOLDER
    model_path = os.path.join(download_root, model)
    if not os.path.exists(model_path):
        if url is None:
            url = f"https://alphacephei.com/vosk/models/{model}.zip"
        download_model(url, download_root)
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
            model = whisper.load_model(model_name, **model_kwargs)
        super().__init__(model, model_name, language, model_kwargs=model_kwargs, **kwargs)

    def transcribe_audio(self, audio_bytes):
        self.log("\nTranscribing")
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).flatten().astype(np.float32) / 32768.0
        return self.model.transcribe(audio_array, fp16=False, language=self.language)

    def finalize(self):
        if len(self.audio_buffer) == 0:
            return {"text": ""}
        result = self.transcribe_audio(self.audio_buffer)
        self.audio_buffer = b''
        return result