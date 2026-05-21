import os

from scribe.backends.openai_api import OpenaiAPITranscriber
from scribe.models import AbstractTranscriber


class GroqTranscriber(OpenaiAPITranscriber):
    name = "groq"
    backend = "groq"
    default_model: str | None = "whisper-large-v3-turbo"

    def __init__(self, model_name="whisper-large-v3-turbo", language=None, model_kwargs={}, model=None,
                 prompt=None, **kwargs):
        if model is None:
            import openai
            model = openai.OpenAI(
                api_key=os.environ.get("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
                timeout=20.0,
            )
        AbstractTranscriber.__init__(self, model, model_name, language, model_kwargs=model_kwargs, **kwargs)
        self._prompt = prompt


def _probe_groq() -> tuple[bool, str | None]:
    if os.environ.get("GROQ_API_KEY"):
        return True, None
    return False, "GROQ_API_KEY not set"
