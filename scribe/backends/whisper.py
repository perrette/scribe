from typing import ClassVar

import numpy as np

from scribe.models import AbstractTranscriber


class WhisperTranscriber(AbstractTranscriber):
    name = "whisper"
    backend = "whisper"
    default_model: str | None = "small"
    is_local: ClassVar[bool] = True

    def __init__(self, model_name, language=None, model=None, model_kwargs={},
                 prompt=None, hotwords=None, dry_run=False, **kwargs):
        if model is None and not dry_run:
            from faster_whisper import WhisperModel
            kw = {"compute_type": "int8", **model_kwargs}
            model = WhisperModel(model_name, **kw)
        super().__init__(model, model_name, language, model_kwargs=model_kwargs,
                         dry_run=dry_run, **kwargs)
        self._prompt = prompt
        self._hotwords = hotwords

    def transcribe_audio(self, audio_bytes):
        self.log("\nTranscribing")
        if self.dry_run:
            # Short-circuit before any faster-whisper call. Still update the
            # rolling chunk-tail context so pseudo-streaming behaves
            # identically to the real path.
            self.dry_run_hits += 1
            text = "[dry-run transcript]"
            self.update_streaming_context(text)
            return {"text": text}
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).flatten().astype(np.float32) / 32768.0
        composed_prompt = self.compose_prompt(self._prompt)
        self.debug_log_request(audio_bytes, model=self.model_name,
                               language=self.language, prompt=composed_prompt,
                               hotwords=self._hotwords)
        segments, _info = self.model.transcribe(
            audio_array,
            language=self.language,
            vad_filter=True,
            beam_size=1,
            initial_prompt=composed_prompt,
            hotwords=self._hotwords,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        )
        text = "".join(segment.text for segment in segments)
        self.update_streaming_context(text)
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
