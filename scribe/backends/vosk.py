import json
from typing import ClassVar

from scribe.models import AbstractStreamingTranscriber, get_vosk_model, get_vosk_recognizer


class VoskTranscriber(AbstractStreamingTranscriber):
    name = "vosk"
    backend = "vosk"
    default_model: str | None = None
    is_local: ClassVar[bool] = True
    supports_streaming: ClassVar[bool] = True
    _frozen_options = frozenset(["pseudo_streaming", "streaming_window",
                                  "silence_duration", "silence_thresh"])

    def __init__(self, model_name, model=None, model_kwargs={}, **kwargs):
        # Vosk has its own internal VAD/segmentation — scribe's silence
        # path is irrelevant. pseudo_streaming defaults to False so the
        # abstract path is inert; pin it here to ignore any caller setting.
        kwargs["pseudo_streaming"] = False
        if model is None:
            model = get_vosk_model(model_name, **model_kwargs)
        super().__init__(model, model_name, model_kwargs=model_kwargs, **kwargs)
        self.recognizer = get_vosk_recognizer(model, self.samplerate)

    def feed_audio(self, chunk=b""):
        self.session.audio_buffer += chunk
        final = self.recognizer.AcceptWaveform(chunk)
        if final:
            result = self.recognizer.Result()
        else:
            result = self.recognizer.PartialResult()
        result_dict = json.loads(result)
        if not final and "text" in result_dict:
            del result_dict["text"]
        # Vosk's `text` is a bare phrase ("hello world"); the app
        # concatenates consecutive `text` events verbatim, so the
        # backend owns its own inter-phrase separator.
        elif final and result_dict.get("text"):
            result_dict["text"] = result_dict["text"] + " "
        yield result_dict

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
    import importlib.util
    if importlib.util.find_spec("vosk") is None:
        return False, "vosk not installed (pip install vosk)"
    return True, None
