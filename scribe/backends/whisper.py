from typing import ClassVar

import numpy as np

from scribe.models import AbstractTranscriber


class WhisperTranscriber(AbstractTranscriber):
    name = "whisper"
    backend = "whisper"
    default_model: str | None = "small"
    is_local: ClassVar[bool] = True

    def __init__(self, model_name, language=None, model=None, model_kwargs={},
                 prompt=None, hotwords=None, **kwargs):
        if model is None:
            from faster_whisper import WhisperModel
            kw = {"compute_type": "int8", **model_kwargs}
            model = WhisperModel(model_name, **kw)
        super().__init__(model, model_name, language, model_kwargs=model_kwargs, **kwargs)
        self._prompt = prompt
        self._hotwords = hotwords

    def transcribe_audio(self, audio_bytes):
        self.log("\nTranscribing")
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).flatten().astype(np.float32) / 32768.0
        segments, _info = self.model.transcribe(
            audio_array,
            language=self.language,
            vad_filter=True,
            beam_size=1,
            initial_prompt=self._prompt,
            hotwords=self._hotwords,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        )
        text = "".join(segment.text for segment in segments)
        return {"text": text}

    def finalize(self):
        if len(self.session.audio_buffer) == 0:
            return {"text": ""}
        result = self.transcribe_audio(self.session.audio_buffer)
        self.session.reset()
        return result


def _probe_whisper() -> tuple[bool, str | None]:
    import importlib.util
    if importlib.util.find_spec("faster_whisper") is None:
        return False, "faster-whisper not installed (pip install faster-whisper)"
    return True, None
