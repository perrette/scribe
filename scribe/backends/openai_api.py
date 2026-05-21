import os
from typing import ClassVar

import numpy as np

from desktop_ai_core.providers.errors import format_openai_error
from scribe.backends.whisper import WhisperTranscriber
from scribe.models import AbstractTranscriber


REALTIME_MODELS = frozenset({"gpt-realtime-whisper"})


class OpenaiAPITranscriber(WhisperTranscriber):
    name = "openai"
    backend = "openai"
    default_model: str | None = "gpt-4o-mini-transcribe"
    is_local: ClassVar[bool] = False

    def __new__(cls, *args, **kwargs):
        if cls is OpenaiAPITranscriber:
            model_name = kwargs.get("model_name")
            if model_name in REALTIME_MODELS:
                from scribe.backends.openai_realtime import OpenaiRealtimeTranscriber
                return OpenaiRealtimeTranscriber(*args, **kwargs)
        return super().__new__(cls)

    def __init__(self, model_name="gpt-4o-mini-transcribe", language=None, model_kwargs={}, model=None,
                 prompt=None, **kwargs):
        if model is None:
            import openai
            model = openai.OpenAI(
                # 20 seconds (default is 10 minutes)
                timeout=20.0,
            )
        AbstractTranscriber.__init__(self, model, model_name, language, model_kwargs=model_kwargs, **kwargs)
        self._prompt = prompt

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
        extra = {"prompt": self._prompt} if self._prompt else {}
        try:
            transcription = self.model.audio.transcriptions.create(
                model=self.model_name,
                file=buffer,
                **extra,
            )
        except openai.OpenAIError as e:
            title, message = format_openai_error(e)
            self.notify_error(title, message)
            return {"text": ""}
        return {"text": transcription.text}


def _probe_openai() -> tuple[bool, str | None]:
    if os.environ.get("OPENAI_API_KEY"):
        return True, None
    return False, "OPENAI_API_KEY not set"
