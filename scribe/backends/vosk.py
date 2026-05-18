import json
import numpy as np

from scribe.models import AbstractTranscriber, get_vosk_model, get_vosk_recognizer


class VoskTranscriber(AbstractTranscriber):
    name = "vosk"
    backend = "vosk"
    default_model: str | None = None
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


def _probe_vosk() -> tuple[bool, str | None]:
    try:
        import vosk  # noqa: F401
        return True, None
    except ImportError as exc:
        return False, f"vosk not installed: {exc}"
