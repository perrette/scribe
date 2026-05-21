import time

from desktop_ai_core.providers import StreamingSTTBackend
from scribe.models import SilenceDetected, StopRecording


class RecordingSession:
    """Holds the recording-lifecycle state for a single voice-to-text session.

    Delegates model calls to the supplied backend (an AbstractTranscriber instance).
    """

    def __init__(self, backend, error_callback=None, logger=None):
        """Initialise lifecycle attributes:

        recording busy waiting interrupt cancelled audio_buffer silence_buffer error_callback .
        """
        self.backend = backend
        backend.session = self
        self.recording = False
        self.busy = False
        self.waiting = False
        self.interrupt = False
        self.cancelled = False
        self.audio_buffer = b''
        self.silence_buffer = b''
        self.start_time = time.time()
        self.last_sound_time = self.start_time
        self.error_callback = error_callback
        if logger is None:
            import logging
            logging.basicConfig(level=logging.INFO)
            logger = logging.getLogger("scribe")
        self.logger = logger

    def notify_error(self, title, message):
        self.log(f"{title}: {message}")
        if self.error_callback is not None:
            try:
                self.error_callback(title, message)
            except Exception as exc:
                self.log(f"error_callback failed: {exc!r}")

    def get_elapsed(self):
        return time.time() - self.start_time

    def is_overtime(self):
        return self.backend.timeout is not None and time.time() - self.start_time > self.backend.timeout

    def reset(self):
        self.audio_buffer = b''
        self.silence_buffer = b''
        self.start_time = time.time()
        reset_model = getattr(self.backend, "reset_model", None)
        if reset_model is not None:
            reset_model()

    def log(self, text):
        if text.startswith("\n"):
            print("")
            text = text[1:]
        if self.logger:
            self.logger.info(text)
        else:
            print(f"[{text}]")

    def start_recording(self, microphone,
                        start_message="Recording... Press Ctrl+C to stop.",
                        stop_message="Exit."):

        self.reset()
        self.interrupt = False
        self.cancelled = False
        self.recording = True
        self.waiting = True
        self.busy = True
        if self.backend.silence_duration is not None:
            self.last_sound_time = time.time() - self.backend.silence_duration
        else:
            self.last_sound_time = time.time()

        streaming = isinstance(self.backend, StreamingSTTBackend)
        if streaming:
            self.backend.open_session(self)

        try:

            with microphone.open_stream():
                self.log(start_message)

                while not self.interrupt:
                    while not microphone.q.empty():
                        data = microphone.q.get()

                        # leave it to each transcriber to handle the silence in audio data
                        try:
                            if streaming:
                                yield from self.backend.feed_audio(data)
                            else:
                                yield self.backend.transcribe_realtime_audio(data)

                        # This exception triggers a pause in recording to allow for a transcription of the audio buffer
                        except SilenceDetected as e:
                            self.log(str(e))
                            self.recording = False  # for the system tray icon
                            try:
                                result = self.backend.finalize()
                            except Exception as exc:
                                self.notify_error("Transcription error", repr(exc))
                                result = {"text": ""}
                            # Do NOT clear microphone.q here: on slow backends
                            # (Groq, OpenAI batch) the round-trip can take 1-2 s,
                            # during which the user is still speaking. Audio in
                            # the queue at this point is their next words —
                            # dropping it loses the tail of the recording.
                            self.reset()
                            yield result
                            self.recording = True  # for the system tray icon
                            self.start_time = time.time()  # reset the start time to avoid timeout

                        if self.is_overtime():
                            raise StopRecording("Overtime: {:.2f} seconds".format(self.get_elapsed()))

                    time.sleep(0.1)  # avoid overheating

        except (KeyboardInterrupt, StopRecording):
            pass

        finally:
            self.waiting = False
            self.recording = False
            if self.cancelled:
                self.reset()
                microphone.q.queue.clear()
                result = {"text": ""}
            else:
                try:
                    result = self.backend.finalize()
                except Exception as exc:
                    self.notify_error("Transcription error", repr(exc))
                    result = {"text": ""}
                    self.reset()
                microphone.q.queue.clear()
            if streaming:
                try:
                    self.backend.close_session()
                except Exception as exc:
                    self.log(f"close_session failed: {exc!r}")
            # Yield before clearing busy so the consumer can finish writing to
            # clipboard / keyboard / file while the icon still shows "busy".
            yield result
            self.busy = False

        self.log(stop_message)
