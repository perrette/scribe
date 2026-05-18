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
        # Set by RecordingSession.__init__; backend reads/writes session.audio_buffer
        # etc. inside transcribe_realtime_audio / finalize.
        self.session = None

    def notify_error(self, title, message):
        if self.session is not None:
            self.session.notify_error(title, message)
        else:
            print(f"[{title}] {message}")

    def log(self, text):
        if self.session is not None:
            self.session.log(text)
        else:
            if text.startswith("\n"):
                print("")
                text = text[1:]
            print(f"[{text}]")

    def transcribe_realtime_audio(self, audio_bytes=b""):
        """This method is generic and assumes the underlying model does not handle real-time audio.
        The Vosk model handles real-time audio, so this method is overridden in the VoskTranscriber class.
        """
        session = self.session

        # Vérifier si le segment est un silence
        if is_silent(audio_bytes, self.silence_thresh):
            session.silence_buffer += audio_bytes
            silence_duration = time.time() - session.last_sound_time
            session.waiting = self.silence_duration is not None and silence_duration >= self.silence_duration

            if session.waiting and len(session.audio_buffer) > 0:
                if self.restart_after_silence:
                    raise SilenceDetected("Silence detected: {:.2f} seconds".format(silence_duration))
                else:
                    raise StopRecording("Silence detected: {:.2f} seconds".format(silence_duration))

        else:
            session.last_sound_time = time.time()
            session.waiting = False
            silence_buffer_data = np.frombuffer(session.silence_buffer, dtype=np.int16)
            # add 0.5 seconds worth of silent data back to the audio buffer
            half_a_second = 0.5
            length_of_half_a_second = int(half_a_second * self.samplerate)
            session.audio_buffer += silence_buffer_data[-length_of_half_a_second:].tobytes() + audio_bytes
            session.silence_buffer = b''

        return {"partial": f"{len(session.audio_buffer)} bytes received (duration: {session.get_elapsed()} seconds)"}

    def transcribe_audio(self, audio_data):
        raise NotImplementedError()

    def finalize(self):
        raise NotImplementedError()


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
        self.session.audio_buffer += audio_bytes
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

    def reset_model(self):
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
        if len(self.session.audio_buffer) == 0:
            return {"text": ""}
        result = self.transcribe_audio(self.session.audio_buffer)
        self.session.reset()
        return result


def _format_openai_error(exc):
    """Turn an openai exception into a (title, message) tuple suited for a user dialog."""
    import openai
    body = getattr(exc, "body", None) or {}
    err = body.get("error") if isinstance(body, dict) else None
    code = (err or {}).get("code") if isinstance(err, dict) else None
    api_message = (err or {}).get("message") if isinstance(err, dict) else None
    detail = api_message or str(exc) or exc.__class__.__name__

    if isinstance(exc, openai.AuthenticationError):
        return "OpenAI authentication failed", f"Check your API key.\n\n{detail}"
    if isinstance(exc, openai.PermissionDeniedError):
        return "OpenAI permission denied", detail
    if isinstance(exc, openai.RateLimitError):
        if code == "insufficient_quota" or "quota" in detail.lower() or "credit" in detail.lower():
            return ("OpenAI credits exhausted",
                    f"Your OpenAI account is out of credits or has hit its quota.\n\n{detail}")
        return "OpenAI rate limit", detail
    if isinstance(exc, openai.APIConnectionError):
        return "OpenAI connection error", f"Could not reach the OpenAI API.\n\n{detail}"
    if isinstance(exc, openai.BadRequestError):
        return "OpenAI bad request", detail
    return f"OpenAI error ({exc.__class__.__name__})", detail


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
        except openai.OpenAIError as e:
            title, message = _format_openai_error(e)
            self.notify_error(title, message)
            return {"text": ""}
        return {"text": transcription.text}
