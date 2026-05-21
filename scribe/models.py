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

    # Pseudo-streaming: trailing chars of previous chunks fed back as
    # `initial_prompt` so whisper has cross-chunk context (capitalization
    # after a period, article gender, language lock). Whisper's prompt
    # window is 224 tokens — ~200 chars of French stays well under it and
    # leaves room for the user's static prompt + words list.
    _STREAMING_CONTEXT_MAX_CHARS = 200

    def __init__(self, model, model_name=None, language=None, samplerate=16000, timeout=None, model_kwargs={},
                 silence_thresh=-40, silence_thresh_onset=-25, silence_duration=0.6,
                 pseudo_streaming=False, streaming_window=5.0):
        self.model_name = model_name
        self.language = language
        self.model = model
        self.model_kwargs = model_kwargs
        self.samplerate = samplerate
        self.timeout = timeout
        # Two thresholds with hysteresis (pseudo-streaming only):
        #   silence_thresh        — used while we're already inside an
        #     utterance. LOW (more negative) so soft trailing syllables
        #     don't get classified as silence and cut the phrase.
        #   silence_thresh_onset  — used when we haven't started capturing
        #     speech yet (audio_buffer empty). HIGH (less negative) so
        #     ambient noise (keyboard, breathing) doesn't kick off a chunk
        #     full of hallucinations.
        # Batch mode ignores silence_thresh_onset.
        self.silence_thresh = silence_thresh
        self.silence_thresh_onset = silence_thresh_onset
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
        # Rolling tail of the previous chunks' transcriptions, fed to the
        # next chunk as prompt context (pseudo-streaming only). Cleared by
        # RecordingSession.start_recording at the start of every new
        # recording; NOT cleared on per-chunk session.reset() (that would
        # defeat the purpose).
        self._streaming_context = ""

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

        # Hysteresis: pick the threshold by speech state. Onset (HIGH) when
        # the buffer is empty — only clearly-louder-than-ambient counts as
        # speech-starting. Pause (LOW) once we've captured speech, so soft
        # trailing syllables don't cut the phrase.
        active_thresh = (self.silence_thresh
                         if session.audio_buffer
                         else self.silence_thresh_onset)
        if is_silent(audio_bytes, active_thresh):
            session.silence_buffer += audio_bytes
            # Cap to max(5s, silence_duration) of trailing silence as a
            # defensive floor — the only consumer (the pre-roll path below)
            # uses just the last 0.5s, but 5s gives headroom for larger
            # silence_duration settings and any future pre-roll change.
            # Without this cap a long pause grows the buffer unboundedly
            # (~2 KB/s at 16 kHz int16 mono → 7 MB/h of silence). 5s caps
            # at 160 KB.
            cap_s = max(5.0, self.silence_duration)
            max_silence_bytes = int(cap_s * self.samplerate) * 2
            if len(session.silence_buffer) > max_silence_bytes:
                session.silence_buffer = session.silence_buffer[-max_silence_bytes:]
            sil_dur = time.time() - session.last_sound_time
            session.waiting = sil_dur >= self.silence_duration

            # Commit on every detected silence pause. The streaming_window
            # is no longer a "wait at least N seconds before cutting" floor —
            # it's only the basis for the force-cut at 2 * window below.
            # session.reset() in the session loop resets start_time on each
            # commit, so `elapsed` here always measures time since the last
            # commit (or start of recording).
            if session.waiting and buffer_ms >= self._CHUNK_MIN_MS:
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

    def compose_prompt(self, base_prompt):
        """Concatenate the user's static prompt with the rolling chunk-tail
        context. Returns None when both are empty so callers can keep the
        backend default. Tail is appended (chronological order) so the
        model sees: [static hints] then [most recent words said].
        """
        tail = self._streaming_context if self.pseudo_streaming else ""
        parts = [p for p in (base_prompt, tail) if p]
        if not parts:
            return None
        return " ".join(parts)

    def update_streaming_context(self, text):
        """Append the latest chunk's text to the rolling context and trim
        to the last `_STREAMING_CONTEXT_MAX_CHARS` characters. No-op in
        batch mode (no chunking → nothing to carry forward).
        """
        if not self.pseudo_streaming:
            return
        text = (text or "").strip()
        if not text:
            return
        combined = f"{self._streaming_context} {text}".strip() if self._streaming_context else text
        if len(combined) > self._STREAMING_CONTEXT_MAX_CHARS:
            combined = combined[-self._STREAMING_CONTEXT_MAX_CHARS:]
        self._streaming_context = combined

    def clear_streaming_context(self):
        self._streaming_context = ""

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
