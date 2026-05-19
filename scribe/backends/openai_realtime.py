import base64
import logging
import os
import queue
import threading
from typing import ClassVar

import numpy as np

from desktop_ai_core.providers.errors import format_openai_error
from scribe.models import AbstractStreamingTranscriber, AbstractTranscriber


log = logging.getLogger(__name__)


class OpenaiRealtimeTranscriber(AbstractStreamingTranscriber):
    name = "openai-realtime"
    backend = "openai-realtime"
    default_model: str | None = "gpt-realtime-whisper"
    is_local: ClassVar[bool] = False
    supports_streaming: ClassVar[bool] = True
    _frozen_options = frozenset(["restart_after_silence", "silence_duration", "silence_thresh"])

    _FINALIZE_TIMEOUT = 5.0
    _CLOSE_JOIN_TIMEOUT = 0.25

    def __init__(self, model_name="gpt-realtime-whisper", language=None, model_kwargs={},
                 model=None, api_key=None, **kwargs):
        # The realtime model has its own VAD; mirror VoskTranscriber and disable
        # scribe's silence-detection path entirely.
        kwargs["silence_thresh"] = -np.inf
        AbstractTranscriber.__init__(
            self, model, model_name, language, model_kwargs=model_kwargs, **kwargs,
        )
        self._api_key = api_key
        self._client = None
        self._connection = None
        self._connection_manager = None
        self._recv_thread = None
        self._event_queue: "queue.Queue[dict]" = queue.Queue()
        self._stop_event = threading.Event()
        self._completed_event = threading.Event()
        self._final_transcript = None
        self._closed = True

    def open_session(self, session):
        import openai

        self._closed = False
        self._stop_event.clear()
        self._completed_event.clear()
        self._final_transcript = None
        self._event_queue = queue.Queue()

        api_key = self._api_key or os.environ.get("OPENAI_API_KEY")
        self._client = openai.OpenAI(api_key=api_key)

        # Per roadmap §E Item 6: POST /realtime/transcription_sessions to
        # validate config before opening the WS. The returned client_secret is
        # only needed for browser-side ephemeral-token flows; with a real API
        # key we open the WS directly and re-send the same config via
        # transcription_session.update.
        self._client.beta.realtime.transcription_sessions.create(
            input_audio_format="pcm16",
            input_audio_transcription={"model": self.model_name},
        )

        self._connection_manager = self._client.beta.realtime.connect(
            model=self.model_name,
            extra_query={"intent": "transcription"},
        )
        self._connection = self._connection_manager.enter()

        self._connection.send({
            "type": "transcription_session.update",
            "session": {
                "input_audio_format": "pcm16",
                "input_audio_transcription": {"model": self.model_name},
            },
        })

        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="openai-realtime-recv", daemon=True,
        )
        self._recv_thread.start()

    def _recv_loop(self):
        """Consume server events off the WS and push translated dicts onto
        ``self._event_queue``. Runs on a background thread — must NOT call
        notify_error / show_error_dialog / any GUI-dispatching code; errors
        are enqueued as ``{"_error": (title, message)}`` for ``feed_audio``
        to dispatch on the recording thread.
        """
        import openai
        try:
            while not self._stop_event.is_set():
                try:
                    event = self._connection.recv()
                except openai.OpenAIError as exc:
                    if not self._stop_event.is_set():
                        self._event_queue.put({"_error": format_openai_error(exc)})
                    break
                except Exception as exc:
                    if not self._stop_event.is_set():
                        self._event_queue.put({
                            "_error": ("Realtime connection lost", repr(exc)),
                        })
                    break

                etype = getattr(event, "type", None)
                if etype == "conversation.item.input_audio_transcription.delta":
                    delta = getattr(event, "delta", None) or ""
                    self._event_queue.put({"partial": delta})
                elif etype == "conversation.item.input_audio_transcription.completed":
                    transcript = getattr(event, "transcript", None) or ""
                    self._final_transcript = transcript
                    self._event_queue.put({"text": transcript})
                    self._completed_event.set()
                elif etype == "conversation.item.input_audio_transcription.failed":
                    err = getattr(event, "error", None)
                    message = (getattr(err, "message", None) if err is not None else None) or str(event)
                    self._event_queue.put({
                        "_error": ("Transcription failed", message),
                    })
                    self._completed_event.set()
                elif etype == "error":
                    err = getattr(event, "error", None)
                    message = (getattr(err, "message", None) if err is not None else None) or str(event)
                    self._event_queue.put({"_error": ("Realtime error", message)})
                else:
                    log.debug("realtime event ignored: %s", etype)
        finally:
            self._completed_event.set()

    def feed_audio(self, chunk=b""):
        self.session.audio_buffer += chunk
        if chunk and self._connection is not None and not self._closed:
            try:
                self._connection.send({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                })
            except Exception as exc:
                self.notify_error("Realtime send failed", repr(exc))

        while True:
            try:
                item = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if "_error" in item:
                title, message = item["_error"]
                self.notify_error(title, message)
                continue
            yield item

    def finalize(self):
        if self._connection is None or self._closed:
            return {"text": self._final_transcript or ""}

        self._completed_event.clear()
        try:
            self._connection.send({"type": "input_audio_buffer.commit"})
        except Exception:
            return {"text": self._final_transcript or ""}

        self._completed_event.wait(timeout=self._FINALIZE_TIMEOUT)
        return {"text": self._final_transcript or ""}

    def close_session(self):
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        self._completed_event.set()

        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass

        if self._recv_thread is not None and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=self._CLOSE_JOIN_TIMEOUT)

        self._connection = None
        self._connection_manager = None
        self._recv_thread = None
        self._client = None

        while True:
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                break


def _probe_openai_realtime() -> tuple[bool, str | None]:
    if os.environ.get("OPENAI_API_KEY"):
        return True, None
    return False, "OPENAI_API_KEY not set"
