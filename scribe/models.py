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

class SilenceDetected(Exception):
    pass

class StopRecording(Exception):
    pass

class AbstractTranscriber:
    backend = None
    _frozen_options = frozenset()
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
        """This method is generic and assumes the underlying model does not handle real-time audio.
        The Vosk model handles real-time audio, so this method is overridden in the VoskTranscriber class.
        """

        # Vérifier si le segment est un silence
        if is_silent(audio_bytes, self.silence_thresh):
            self.silence_buffer += audio_bytes
            silence_duration = time.time() - self.last_sound_time
            self.waiting = self.silence_duration is not None and silence_duration >= self.silence_duration

            if self.waiting and len(self.audio_buffer) > 0:
                if self.restart_after_silence:
                    raise SilenceDetected("Silence detected: {:.2f} seconds".format(silence_duration))
                else:
                    raise StopRecording("Silence detected: {:.2f} seconds".format(silence_duration))

        else:
            self.last_sound_time = time.time()
            self.waiting = False
            silence_buffer_data = np.frombuffer(self.silence_buffer, dtype=np.int16)
            # add 0.5 seconds worth of silent data back to the audio buffer
            half_a_second = 0.5
            length_of_half_a_second = int(half_a_second * self.samplerate)
            self.audio_buffer += silence_buffer_data[-length_of_half_a_second:].tobytes() + audio_bytes
            self.silence_buffer = b''

        return {"partial": f"{len(self.audio_buffer)} bytes received (duration: {self.get_elapsed()} seconds)"}

    def transcribe_audio(self, audio_data):
        raise NotImplementedError()

    def reset(self):
        self.audio_buffer = b''
        self.start_time = time.time()
        self.silence_buffer = b''

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
        # self.silence_buffer = b'' # already reset in self.reset()

        try:

            with microphone.open_stream():
                self.log(start_message)

                while not self.interrupt:
                    while not microphone.q.empty():
                        data = microphone.q.get()

                        # leave it to each transcriber to handle the silence in audio data
                        try:
                            yield self.transcribe_realtime_audio(data)

                        # This exception triggers a pause in recording to allow for a transcription of the audio buffer
                        except SilenceDetected as e:
                            self.log(str(e))
                            self.recording = False # for the system tray icon
                            result = self.finalize()
                            microphone.q.queue.clear()
                            self.reset()
                            yield result
                            self.recording = True # for the system tray icon
                            self.start_time = time.time() # reset the start time to avoid timeout

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
    _frozen_options = frozenset(["restart_after_silence", "silence_duration", "silence_thresh"])

    def __init__(self, model_name, model=None, model_kwargs={}, **kwargs):
        kwargs["silence_thresh"] = -np.inf  # disable silence detection (this is handled by Vosk)
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
        self.reset()
        return result


class OpenaiAPITranscriber(WhisperTranscriber):
    backend = "openaiapi"

    def __init__(self, model_name="whisper-1", language=None, model_kwargs={}, model=None, api_key=None, **kwargs):
        if model is None:
            import openai
            model = openai.OpenAI(
                api_key=api_key or openai.api_key,
                # 20 seconds (default is 10 minutes)
                timeout=20.0,
            )
        AbstractTranscriber.__init__(self, model, model_name, language, model_kwargs=model_kwargs, **kwargs)

    def transcribe_audio(self, audio_bytes):
        self.log("\nTranscribing")
        import io
        import openai
        import soundfile as sf
        audio_data = np.frombuffer(audio_bytes, dtype=np.int16).flatten().astype(np.float32) / 32768.0
        # Write the audio data to an in-memory file in WAV format
        buffer = io.BytesIO()
        sf.write(buffer, audio_data, self.samplerate, format='WAV')
        buffer.seek(0)
        buffer.name = "audio.wav"  # Set a filename with a valid extension
        try:
            transcription = self.model.audio.transcriptions.create(
                model=self.model_name,
                file=buffer,
            )
        except openai.BadRequestError as e:
            self.log(f"Error: {e}")
            return {"text": ""}
        return {"text": transcription.text}
