import os
import numpy as np

from scribe.backends.whisper import WhisperTranscriber
from scribe.models import AbstractTranscriber


def _format_openai_error(exc):
    """Turn an openai exception into a (title, message) tuple suited for a user dialog."""
    import openai
    body = getattr(exc, "body", None) or {}
    err = body.get("error") if isinstance(body, dict) else None
    code = (err or {}).get("code") if isinstance(err, dict) else None
    api_message = (err or {}).get("message") if isinstance(err, dict) else None
    detail = api_message or str(exc) or exc.__class__.__name__

    if isinstance(exc, openai.AuthenticationError):
        return "OpenAI authentication failed", f"Check your API key.\n\n{detail}"
    if isinstance(exc, openai.PermissionDeniedError):
        return "OpenAI permission denied", detail
    if isinstance(exc, openai.RateLimitError):
        if code == "insufficient_quota" or "quota" in detail.lower() or "credit" in detail.lower():
            return ("OpenAI credits exhausted",
                    f"Your OpenAI account is out of credits or has hit its quota.\n\n{detail}")
        return "OpenAI rate limit", detail
    if isinstance(exc, openai.APIConnectionError):
        return "OpenAI connection error", f"Could not reach the OpenAI API.\n\n{detail}"
    if isinstance(exc, openai.BadRequestError):
        return "OpenAI bad request", detail
    return f"OpenAI error ({exc.__class__.__name__})", detail


class OpenaiAPITranscriber(WhisperTranscriber):
    name = "openaiapi"
    backend = "openaiapi"
    default_model: str | None = "whisper-1"

    def __init__(self, model_name="whisper-1", language=None, model_kwargs={}, model=None, api_key=None, **kwargs):
        if model is None:
            import openai
            model = openai.OpenAI(
                api_key=api_key or openai.api_key,
                # 20 seconds (default is 10 minutes)
                timeout=20.0,
            )
        AbstractTranscriber.__init__(self, model, model_name, language, model_kwargs=model_kwargs, **kwargs)

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
        try:
            transcription = self.model.audio.transcriptions.create(
                model=self.model_name,
                file=buffer,
            )
        except openai.OpenAIError as e:
            title, message = _format_openai_error(e)
            self.notify_error(title, message)
            return {"text": ""}
        return {"text": transcription.text}


def _probe_openai() -> tuple[bool, str | None]:
    if os.environ.get("OPENAI_API_KEY"):
        return True, None
    return False, "OPENAI_API_KEY not set"
