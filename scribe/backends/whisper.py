import numpy as np

from scribe.models import AbstractTranscriber


class WhisperTranscriber(AbstractTranscriber):
    name = "whisper"
    backend = "whisper"
    default_model: str | None = "small"

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


def _probe_whisper() -> tuple[bool, str | None]:
    try:
        import whisper  # noqa: F401
        return True, None
    except ImportError as exc:
        return False, f"whisper not installed: {exc}"
