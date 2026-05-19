import os
import time
from pathlib import Path
import numpy as np
from desktop_ai_core.providers import STTBackend, StreamingSTTBackend
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

class AbstractTranscriber(STTBackend):
    name: str = ""
    default_model: str | None = None
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

    def transcribe(self, audio_path) -> str:
        """Implement the shared `STTBackend.transcribe(audio_path)` contract by
        loading the WAV at `audio_path` and delegating to `transcribe_audio`.
        Scribe itself drives transcription through `transcribe_realtime_audio`
        / `finalize`; this is the path bard-style consumers go through.
        """
        import soundfile as sf
        audio_data, _ = sf.read(str(Path(audio_path)), dtype="int16")
        result = self.transcribe_audio(audio_data.tobytes())
        if isinstance(result, dict):
            return result.get("text", "") or ""
        return str(result)


class AbstractStreamingTranscriber(AbstractTranscriber, StreamingSTTBackend):
    """Shared base for streaming transcribers in scribe.

    Inherits scribe's session/notify_error/log plumbing from
    `AbstractTranscriber` and the streaming protocol (`feed_audio`,
    `open_session`, `close_session`) from `StreamingSTTBackend`. The
    backward-compat `transcribe_realtime_audio` adapter is taken from
    `StreamingSTTBackend` (drains `feed_audio` and returns the last
    event), overriding `AbstractTranscriber`'s buffering version which
    only makes sense for batch backends.
    """

    def transcribe_realtime_audio(self, chunk=b""):
        return StreamingSTTBackend.transcribe_realtime_audio(self, chunk)


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
