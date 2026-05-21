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

    # Pseudo-streaming: don't cut a chunk smaller than this. Whisper-family
    # models hallucinate on very short clips ("Not to know.", "Thanks for
    # watching!", etc. on near-silence), so the floor exists for quality,
    # not just to avoid API rejection. 1.5 s gives Whisper enough context
    # to anchor on real content and emit no_speech_prob > threshold on
    # silence. Sub-threshold accumulations stay in the buffer until more
    # audio arrives.
    _CHUNK_MIN_MS = 1500.0

    def __init__(self, model, model_name=None, language=None, samplerate=16000, timeout=None, model_kwargs={},
                 silence_thresh=-40, silence_duration=0.6,
                 pseudo_streaming=False, streaming_window=5.0):
        self.model_name = model_name
        self.language = language
        self.model = model
        self.model_kwargs = model_kwargs
        self.samplerate = samplerate
        self.timeout = timeout
        self.silence_thresh = silence_thresh
        self.silence_duration = silence_duration
        # Pseudo-streaming (experimental): when on, transcribe_realtime_audio
        # cuts the running buffer into chunks driven by silence + a target
        # window. When off, transcribe_realtime_audio just accumulates and
        # finalize() transcribes the whole recording.
        self.pseudo_streaming = pseudo_streaming
        self.streaming_window = streaming_window
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
        """Generic adapter for batch backends. Two modes:

        - Default (pseudo_streaming=False): accumulate the whole recording
          into session.audio_buffer; finalize() runs one transcription.
        - Pseudo-streaming (pseudo_streaming=True, experimental): cut the
          running buffer into chunks. First-fit silence cut once the buffer
          has accumulated >= streaming_window seconds; force-cut at
          2 * streaming_window. Cuts raise SilenceDetected; the session
          loop catches that, calls finalize(), and resumes.

        Streaming backends (Vosk, OpenAI realtime) override this — they
        feed audio incrementally to their own engines and never hit this
        path.
        """
        session = self.session

        if not self.pseudo_streaming:
            session.audio_buffer += audio_bytes
            return {"partial": f"{len(session.audio_buffer)} bytes received "
                               f"(duration: {session.get_elapsed():.2f} seconds)"}

        elapsed = time.time() - session.start_time
        buffer_ms = (len(session.audio_buffer) / 2) / self.samplerate * 1000.0

        if is_silent(audio_bytes, self.silence_thresh):
            session.silence_buffer += audio_bytes
            sil_dur = time.time() - session.last_sound_time
            session.waiting = sil_dur >= self.silence_duration

            if (elapsed >= self.streaming_window
                    and session.waiting
                    and buffer_ms >= self._CHUNK_MIN_MS):
                raise SilenceDetected(
                    f"Cut at silence after {elapsed:.2f}s "
                    f"(silent {sil_dur:.2f}s)"
                )
        else:
            session.last_sound_time = time.time()
            session.waiting = False
            silence_buffer_data = np.frombuffer(session.silence_buffer, dtype=np.int16)
            # Add 0.5s of trailing silence back so word boundaries aren't clipped.
            length_of_half_a_second = int(0.5 * self.samplerate)
            session.audio_buffer += silence_buffer_data[-length_of_half_a_second:].tobytes() + audio_bytes
            session.silence_buffer = b''

        if elapsed >= 2 * self.streaming_window and buffer_ms >= self._CHUNK_MIN_MS:
            raise SilenceDetected(
                f"Force-cut at 2x streaming window ({elapsed:.2f}s)"
            )

        return {"partial": f"{len(session.audio_buffer)} bytes received "
                           f"(duration: {elapsed:.2f} seconds)"}

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
