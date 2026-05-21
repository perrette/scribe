import base64
import logging
import os
import queue
import threading
from typing import ClassVar

import numpy as np

from desktop_ai_core.providers.errors import format_openai_error
from scribe.models import AbstractStreamingTranscriber, AbstractTranscriber, is_silent


log = logging.getLogger(__name__)


class OpenaiRealtimeTranscriber(AbstractStreamingTranscriber):
    name = "openai"
    backend = "openai"
    default_model: str | None = "gpt-realtime-whisper"
    is_local: ClassVar[bool] = False
    supports_streaming: ClassVar[bool] = True
    _frozen_options = frozenset(["pseudo_streaming", "streaming_window"])

    _FINALIZE_TIMEOUT = 5.0
    _CLOSE_JOIN_TIMEOUT = 0.25

    # OpenAI GA realtime PCM only supports 24 kHz; scribe records at 16 kHz, so
    # feed_audio upsamples int16 frames before send.
    _GA_SAMPLE_RATE = 24000

    # Server-side commit() rejects buffers under 100ms with
    # "buffer too small. Expected at least 100ms of audio". Track sent
    # audio duration and skip commits below this — a tiny burst (cough,
    # click) followed by silence would otherwise trigger an error popup.
    _SERVER_COMMIT_MIN_MS = 100.0

    def __init__(self, model_name="gpt-realtime-whisper", language=None, model_kwargs={},
                 model=None, api_key=None, realtime_delay="medium",
                 realtime_gate=True, prompt=None, **kwargs):
        AbstractTranscriber.__init__(
            self, model, model_name, language, model_kwargs=model_kwargs, **kwargs,
        )
        self._prompt = prompt
        # Client-side silence gate: gpt-realtime-whisper has no server VAD
        # (turn_detection is None in _session_config), so every audio frame
        # we send is billed as input audio — including silence. When
        # enabled, feed_audio drops frames quieter than silence_thresh.
        self._gate_enabled = realtime_gate
        # Without server VAD the model also keeps trailing words in a
        # tentative buffer until something commits; mid-session commit
        # flushes the trailing deltas live so the user sees the end of
        # their phrase without having to stop the recording. Triggered
        # after silence_duration seconds of sustained silence.
        self._api_key = api_key
        self._realtime_delay = realtime_delay
        self._client = None
        self._connection = None
        self._connection_manager = None
        self._recv_thread = None
        self._event_queue: "queue.Queue[dict]" = queue.Queue()
        self._stop_event = threading.Event()
        self._completed_event = threading.Event()
        self._final_transcript = None
        self._closed = True
        self._resample_tail: np.ndarray = np.zeros(0, dtype=np.int16)
        # Mid-session auto-commit state.
        self._has_uncommitted_audio = False
        self._silent_samples = 0
        self._uncommitted_ms = 0.0

    def _session_config(self) -> dict:
        # gpt-realtime-whisper does NOT support server VAD (rejected as
        # "Turn detection is not supported for this transcription model").
        # The streaming knob for this model is `delay` — "minimal" emits
        # partials as early as possible; higher values trade latency for
        # accuracy. Surfaced as the --realtime-delay CLI flag.
        transcription: dict = {"model": self.model_name, "delay": self._realtime_delay}
        if self.language:
            transcription["language"] = self.language
        if self._prompt:
            transcription["prompt"] = self._prompt
        audio_input: dict = {
            "format": {"type": "audio/pcm", "rate": self._GA_SAMPLE_RATE},
            "transcription": transcription,
            "turn_detection": None,
        }
        return {
            "type": "transcription",
            "audio": {"input": audio_input},
        }

    def open_session(self, session):
        import openai

        self._closed = False
        self._stop_event.clear()
        self._completed_event.clear()
        self._final_transcript = None
        self._event_queue = queue.Queue()
        self._resample_tail = np.zeros(0, dtype=np.int16)
        self._has_uncommitted_audio = False
        self._silent_samples = 0
        self._uncommitted_ms = 0.0

        api_key = self._api_key or os.environ.get("OPENAI_API_KEY")
        self._client = openai.OpenAI(api_key=api_key)

        # GA flow: POST /v1/realtime/client_secrets to validate config (the
        # ephemeral secret it returns is for browser-side flows; with a real
        # API key we connect directly and resend the same config via
        # session.update).
        session_config = self._session_config()
        self._client.realtime.client_secrets.create(session=session_config)

        # GA transcription WS: `?intent=transcription` discriminator, no
        # `model=` query (the transcription model lives in session.update).
        # The `OpenAI-Beta` header is what was retired — the URL shape with
        # intent=transcription carried over to GA unchanged.
        self._connection_manager = self._client.realtime.connect(
            extra_query={"intent": "transcription"},
        )
        self._connection = self._connection_manager.enter()
        self._connection.session.update(session=session_config)

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
                    # gpt-realtime-whisper deltas are append-only token
                    # fragments — already-committed text, just delivered in
                    # fine-grained pieces. Route them as `text` so scribe's
                    # live-paste path types each token as it arrives, the
                    # same UX Vosk gets from its per-phrase commits.
                    delta = getattr(event, "delta", None) or ""
                    self._event_queue.put({"text": delta})
                elif etype == "conversation.item.input_audio_transcription.completed":
                    # The session-end `.completed` carries the full
                    # transcript, but every token has already been yielded
                    # as a `text` delta above — re-emitting it would paste
                    # the entire utterance again. Only keep the final
                    # transcript for finalize()'s return value.
                    self._final_transcript = getattr(event, "transcript", None) or ""
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

    def _upsample_to_ga(self, chunk: bytes) -> bytes:
        """Resample int16 mono PCM from self.samplerate to 24 kHz.

        Carries a one-sample tail across chunks so interpolated boundaries
        don't pop. Returns b"" if there is nothing to send yet.
        """
        if not chunk:
            return b""
        src_rate = self.samplerate
        dst_rate = self._GA_SAMPLE_RATE
        samples = np.frombuffer(chunk, dtype=np.int16)
        if src_rate == dst_rate:
            return samples.tobytes()
        # Prepend one sample of tail so linear interp is continuous across chunks.
        joined = np.concatenate([self._resample_tail, samples])
        if joined.size < 2:
            self._resample_tail = joined
            return b""
        # Indices in the source space, mapped from a uniform 24 kHz grid.
        n_out = int((joined.size - 1) * dst_rate / src_rate)
        if n_out <= 0:
            self._resample_tail = joined[-1:]
            return b""
        x_new = np.arange(n_out, dtype=np.float64) * (src_rate / dst_rate)
        x_old = np.arange(joined.size, dtype=np.float64)
        y_new = np.interp(x_new, x_old, joined.astype(np.float64))
        self._resample_tail = joined[-1:]
        return np.clip(y_new, -32768, 32767).astype(np.int16).tobytes()

    def feed_audio(self, chunk=b""):
        self.session.audio_buffer += chunk
        if chunk and self._connection is not None and not self._closed:
            chunk_is_silent = is_silent(chunk, self.silence_thresh)

            # Send unless the gate is on and the chunk is silent.
            if not (chunk_is_silent and self._gate_enabled):
                try:
                    payload = self._upsample_to_ga(chunk)
                    if payload:
                        self._connection.input_audio_buffer.append(
                            audio=base64.b64encode(payload).decode("ascii"),
                        )
                        self._has_uncommitted_audio = True
                        # Track sent audio in ms (int16 → 2 bytes/sample).
                        self._uncommitted_ms += (len(payload) / 2) / self._GA_SAMPLE_RATE * 1000.0
                except Exception as exc:
                    self.notify_error("Realtime send failed", repr(exc))

            # Silence tracking for the mid-session auto-commit; driven by
            # silence regardless of whether the gate dropped the frame.
            if chunk_is_silent:
                if self._has_uncommitted_audio:
                    self._silent_samples += len(chunk) // 2  # int16 → 2 bytes
                    commit_samples = int(self.silence_duration * self.samplerate)
                    if commit_samples > 0 and self._silent_samples >= commit_samples:
                        # Server rejects commits below _SERVER_COMMIT_MIN_MS;
                        # leave a sub-threshold burst in the buffer for the
                        # next speech to extend.
                        if self._uncommitted_ms >= self._SERVER_COMMIT_MIN_MS:
                            try:
                                self._connection.input_audio_buffer.commit()
                            except Exception as exc:
                                log.debug("mid-session commit failed: %s", exc)
                            self._has_uncommitted_audio = False
                            self._uncommitted_ms = 0.0
                        self._silent_samples = 0
            else:
                self._silent_samples = 0

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
            return {"text": ""}

        # Only commit + wait if there's audio the model hasn't flushed yet
        # AND the buffer is over the server's 100ms minimum. If the
        # mid-session silence auto-commit already fired, the buffer is
        # empty; if a sub-threshold burst is sitting in the buffer,
        # commit would error and we'd block waiting for a `.completed`
        # that never arrives.
        if (self._has_uncommitted_audio
                and self._uncommitted_ms >= self._SERVER_COMMIT_MIN_MS):
            self._completed_event.clear()
            try:
                self._connection.input_audio_buffer.commit()
            except Exception:
                return {"text": ""}
            self._has_uncommitted_audio = False
            self._uncommitted_ms = 0.0
            # Wait for the server's `.completed` event; trailing deltas
            # land on the queue between commit and completion. The
            # recording loop has already exited, so drain the queue here
            # and stitch the tail together — otherwise the last words
            # spoken just before stop get dropped. The bulk of the
            # transcript was already streamed live as `text` deltas during
            # recording, so we only return the tail.
            self._completed_event.wait(timeout=self._FINALIZE_TIMEOUT)
        tail_parts: list[str] = []
        while True:
            try:
                item = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if "_error" in item:
                title, message = item["_error"]
                self.notify_error(title, message)
                continue
            text = item.get("text")
            if text:
                tail_parts.append(text)
        return {"text": "".join(tail_parts)}

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


