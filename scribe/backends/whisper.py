from typing import ClassVar

import numpy as np

from scribe.models import AbstractTranscriber


class WhisperTranscriber(AbstractTranscriber):
    name = "whisper"
    backend = "whisper"
    default_model: str | None = "large-v3-turbo"
    is_local: ClassVar[bool] = True

    def __init__(self, model_name, language=None, model=None, model_kwargs={}, **kwargs):
        if model is None:
            from faster_whisper import WhisperModel
            kw = {"compute_type": "int8", **model_kwargs}
            model = WhisperModel(model_name, **kw)
        super().__init__(model, model_name, language, model_kwargs=model_kwargs, **kwargs)

    def transcribe_audio(self, audio_bytes):
        self.log("\nTranscribing")
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).flatten().astype(np.float32) / 32768.0
        segments, _info = self.model.transcribe(audio_array, language=self.language)
        text = "".join(segment.text for segment in segments)
        return {"text": text}

    def finalize(self):
        if len(self.session.audio_buffer) == 0:
            return {"text": ""}
        result = self.transcribe_audio(self.session.audio_buffer)
        self.session.reset()
        return result


def _probe_whisper() -> tuple[bool, str | None]:
    try:
        import faster_whisper  # noqa: F401
        return True, None
    except ImportError as exc:
        return False, f"faster-whisper not installed: {exc}"
