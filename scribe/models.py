import math
import os
import time
from pathlib import Path
import numpy as np
from desktop_ai_core.providers import STTBackend, StreamingSTTBackend
from scribe.util import download_model
from scribe.audio import calculate_decibels, make_silence_gate

def is_silent(data, silence_thresh=-40):
    """
    Détermine si un segment audio est un silence en fonction du niveau de volume.
    """
    return calculate_decibels(data) < silence_thresh

HOME = os.environ.get('HOME', os.path.expanduser('~'))
XDG_CACHE_HOME = os.environ.get('XDG_CACHE_HOME', os.path.join(HOME, '.cache'))
VOSK_MODELS_FOLDER = os.path.join(XDG_CACHE_HOME, "vosk")

class SilenceDetected(Exception):
    pass

class StopRecording(Exception):
    pass

class AbstractTranscriber(STTBackend):
    name: str = ""
    default_model: str | None = None
    backend = None
    _frozen_options = frozenset()

    def __init__(self, model, model_name=None, language=None, samplerate=16000, timeout=None, model_kwargs={},
                 silence_thresh=-40, stream_chunk_silence_break=0.6, realtime_commit_silence=0.6,
                 vad_mode="auto", vad_threshold=0.5, vad_min_silence_ms=300,
                 pseudo_streaming=False, stream_chunk_max=10.0,
                 stream_chunk_min=1.5, stream_first_chunk_min=3.0,
                 stream_context_reset_silence=3.0,
                 stream_context_length=200,
                 clip_max_silence=2.0,
                 dry_run=False, debug=False):
        self.model_name = model_name
        self.language = language
        self.model = model
        self.model_kwargs = model_kwargs
        self.samplerate = samplerate
        self.timeout = timeout
        # When True, every backend short-circuits the network/model request
        # right before the boundary (SDK / WS / whisper.cpp / vosk decode)
        # and returns a canned transcript instead. The recording session,
        # silence-cut logic, chunk emission, and keystroke/clipboard output
        # all run normally — only the actual STT call is stubbed. Used by
        # tests/test_backend_matrix.py to verify the recording pipeline
        # across every (backend, mode) cell without needing network access
        # or every model on disk.
        self.dry_run = dry_run
        # Counter incremented every time a backend's dry-run branch
        # short-circuits the request boundary. Test harnesses use this
        # to confirm the boundary was reached (cf. _intercept_fired in
        # tests/test_backend_matrix.py). Stays 0 in normal operation.
        self.dry_run_hits = 0
        # silence_thresh (dB mode only) — single volume floor used as a
        # no-dependency fallback. The old onset/sustain hysteresis was a
        # hack to make volume-only detection survive ambient noise; silero
        # does that properly. dB stays simple by design.
        self.silence_thresh = silence_thresh
        self.stream_chunk_silence_break = stream_chunk_silence_break
        self.realtime_commit_silence = realtime_commit_silence
        # VAD configuration. `vad_mode` picks the SilenceGate implementation
        # in scribe/audio.py:
        #   "auto"   — prefer silero if installed, fall back to dB.
        #   "db"     — volume-only threshold (the legacy gate).
        #   "silero" — silero-vad, robust to ambient noise + soft speech.
        # The vad_* knobs are passed through to silero's VADIterator and
        # ignored in dB mode. "auto" is resolved here, eagerly, so the rest
        # of the codebase only ever sees a concrete mode.
        if vad_mode == "auto":
            try:
                import onnxruntime  # noqa: F401
                from scribe.audio import _bundled_silero_onnx_path
                if not _bundled_silero_onnx_path().exists():
                    raise ImportError("bundled silero_vad.onnx not found")
                vad_mode = "silero"
                self._vad_auto_log = "VAD: silero (auto-selected)"
            except (ImportError, FileNotFoundError) as exc:
                # onnxruntime is a base dependency now, so this path means
                # the install is broken (missing model file, custom slim
                # build, frozen env without it). Fall back to dB and surface
                # the actual reason rather than the old "install [vad]" hint.
                vad_mode = "db"
                self._vad_auto_log = (
                    f"VAD: silero unavailable ({exc}); falling back to dB threshold"
                )
        else:
            self._vad_auto_log = None
        self.vad_mode = vad_mode
        self.vad_threshold = vad_threshold
        self.vad_min_silence_ms = vad_min_silence_ms
        self._silence_gate = None
        # Pseudo-streaming (experimental): when on, transcribe_realtime_audio
        # cuts the running buffer into chunks driven by silence + a target
        # window. When off, transcribe_realtime_audio just accumulates and
        # finalize() transcribes the whole recording.
        self.pseudo_streaming = pseudo_streaming
        self.stream_chunk_max = stream_chunk_max
        self.stream_chunk_min = stream_chunk_min
        # First-chunk minimum: applies to the very first chunk of a
        # streaming thread (recording start, or just after a context-reset
        # silence cleared `_streaming_context`). A higher floor here forces
        # the first chunk to accumulate enough audio that Whisper can
        # produce a properly-punctuated bootstrap transcript — the tail of
        # which then seeds the rolling prompt for every chunk after it.
        # Default 3 s vs. the regular 1.5 s: short pauses inside the first
        # phrase no longer cut the chunk too early; subsequent chunks stay
        # responsive at 1.5 s. Clamped to <= stream_chunk_max at use time
        # so misconfiguration can't deadlock the chunker.
        self.stream_first_chunk_min = stream_first_chunk_min
        self.stream_context_reset_silence = stream_context_reset_silence
        # Pseudo-streaming: cap on the rolling cross-chunk prompt context
        # in characters. Whisper's prompt window is 224 tokens, so ~200
        # chars of French stays well under it and leaves room for the
        # user's static prompt + words list. 0 disables the rolling
        # context entirely (each chunk transcribes without any cross-
        # chunk prompt) — the OFF semantic surfaced as a picker value.
        self.stream_context_length = stream_context_length
        # Clip mode: cap each silent pause at this many seconds in the
        # accumulated recording. Remote APIs bill by audio duration (the
        # WAV sent is uncompressed), and Whisper reads no meaning into
        # pauses beyond a couple of seconds — long silences only add cost,
        # local processing time, and hallucination risk. 0 (or negative)
        # disables trimming and accumulates the recording verbatim.
        self.clip_max_silence = clip_max_silence
        # When True, each backend logs a one-line summary of the request
        # being sent (model, language, prompt, audio length) just before
        # the network/SDK call. Driven by the `--debug` CLI flag — off by
        # default so production output stays clean.
        self.debug = debug
        # Set by RecordingSession.__init__; backend reads/writes session.audio_buffer
        # etc. inside transcribe_realtime_audio / finalize.
        self.session = None
        # Rolling tail of the previous chunks' transcriptions, fed to the
        # next chunk as prompt context (pseudo-streaming only). Cleared by
        # RecordingSession.start_recording at the start of every new
        # recording; NOT cleared on per-chunk session.reset() (that would
        # defeat the purpose).
        self._streaming_context = ""
        # Auto-mode chunk handover. When a force-cut re-cuts the audio
        # buffer at the best in-window silence, the trailing audio (post-
        # cut) lives here until the next transcribe_realtime_audio call
        # injects it into the new chunk's session.audio_buffer. Must
        # survive session.reset() (which runs between the cut and the
        # next call), so it lives on the backend, not on the session.
        self._pending_chunk_audio = b''
        if self._vad_auto_log:
            self.log(self._vad_auto_log)

    @property
    def silence_gate(self):
        """Lazily construct the SilenceGate from current vad_* settings.
        Lazy because the silero gate loads an ONNX model on first use (~80
        ms) and we want that cost only when something actually needs it
        — e.g. clip mode with --clip-max-silence 0 never touches it.
        Invalidated on `_invalidate_silence_gate()` so menu/settings changes
        take effect on the next use."""
        if self._silence_gate is None:
            self._silence_gate = make_silence_gate(
                mode=self.vad_mode,
                samplerate=self.samplerate,
                silence_thresh=self.silence_thresh,
                vad_threshold=self.vad_threshold,
                vad_min_silence_ms=self.vad_min_silence_ms,
            )
        return self._silence_gate

    def _invalidate_silence_gate(self):
        """Drop the cached gate so the next access rebuilds from current
        settings. Call after changing vad_mode or any vad_* knob from
        the menu / API."""
        self._silence_gate = None

    def notify_error(self, title, message):
        if self.session is not None:
            self.session.notify_error(title, message)
        else:
            print(f"[{title}] {message}")

    def log(self, text):
        if self.session is not None:
            self.session.log(text)
        else:
            if text.startswith("\n"):
                print("")
                text = text[1:]
            print(f"[{text}]")

    def debug_log_request(self, audio_bytes=None, **params):
        """One-line summary of the request a backend is about to send, gated
        on ``self.debug`` (``--debug`` CLI flag). Off by default. Values are
        ``repr``-ed so callers don't have to pre-format strings, and the
        composed prompt is truncated at 200 chars to keep the line scannable
        when long word lists are in play. ``audio_bytes`` is optional — when
        passed, its duration in seconds is appended (computed from
        ``samplerate`` × 2 for int16). The single call site per backend
        lives just before the SDK / network boundary so what is logged is
        what is actually about to be sent."""
        if not self.debug:
            return
        parts = [f"backend={self.backend}"]
        for key, value in params.items():
            if isinstance(value, str) and len(value) > 200:
                value = value[:197] + "..."
            parts.append(f"{key}={value!r}")
        if audio_bytes is not None:
            duration = len(audio_bytes) / (self.samplerate * 2)
            parts.append(f"audio_s={duration:.2f}")
        self.log("req " + " ".join(parts))

    def transcribe_realtime_audio(self, audio_bytes=b""):
        """Generic adapter for batch backends. Two modes:

        - Default (pseudo_streaming=False): accumulate the recording into
          session.audio_buffer; finalize() runs one transcription. Silent
          pauses are capped at clip_max_silence seconds each (see __init__)
          so dead air never inflates what is sent for transcription.
        - Pseudo-streaming (pseudo_streaming=True, experimental): cut the
          running buffer into chunks. Silence-cut when a pause >= silence
          duration is detected; force-cut at stream_chunk_max seconds.
          Cuts raise SilenceDetected; the session loop catches that, calls
          finalize(), and resumes.

        Streaming backends (Vosk, OpenAI realtime) override this — they
        feed audio incrementally to their own engines and never hit this
        path.
        """
        session = self.session

        if not self.pseudo_streaming:
            # Clip mode. Divert gate-silent blocks to session.silence_buffer
            # and, when speech resumes, re-add only its tail — each pause in
            # the accumulated audio is at most clip_max_silence seconds.
            # Keeping the *tail* of the pause preserves the stretch right
            # before the next word's onset (the word-boundary protection the
            # streaming path gets from its 0.5 s re-add); trailing silence at
            # stop-recording is dropped entirely since finalize() only reads
            # audio_buffer.
            if self.clip_max_silence <= 0:
                session.audio_buffer += audio_bytes
            elif self.silence_gate.is_silent(
                    audio_bytes, in_utterance=bool(session.audio_buffer)):
                session.silence_buffer += audio_bytes
                max_silence_bytes = (
                    int(self.clip_max_silence * self.samplerate) * 2)
                if len(session.silence_buffer) > max_silence_bytes:
                    session.trimmed_silence_bytes = (
                        getattr(session, "trimmed_silence_bytes", 0)
                        + len(session.silence_buffer) - max_silence_bytes)
                    session.silence_buffer = \
                        session.silence_buffer[-max_silence_bytes:]
                # Same waiting semantics as the streaming path: the tray
                # icon flips back to plain "recording" after a silence-
                # break worth of quiet. silence-break can be 0 (Auto) or
                # None (Max) — fall back to the 0.6 s default.
                session.waiting = (
                    time.time() - session.last_sound_time
                    >= (self.stream_chunk_silence_break or 0.6))
            else:
                session.audio_buffer += session.silence_buffer + audio_bytes
                session.silence_buffer = b''
                session.last_sound_time = time.time()
                session.waiting = False
            partial = (f"{len(session.audio_buffer)} bytes received "
                       f"(duration: {session.get_elapsed():.2f} seconds")
            trimmed_s = (getattr(session, "trimmed_silence_bytes", 0)
                         / (self.samplerate * 2))
            if trimmed_s:
                partial += f", trimmed {trimmed_s:.1f}s silence"
            return {"partial": partial + ")"}

        # Auto-mode handover: if the previous call's force-cut produced
        # trailing audio (the post-silence remainder we couldn't fit in
        # the just-finalised chunk), prepend it now before any length
        # math runs.
        if self._pending_chunk_audio:
            session.audio_buffer += self._pending_chunk_audio
            self._pending_chunk_audio = b''

        elapsed = time.time() - session.start_time
        buffer_ms = (len(session.audio_buffer) / 2) / self.samplerate * 1000.0

        silence_break = self.stream_chunk_silence_break
        auto_mode = silence_break == 0
        max_mode = silence_break is None
        fixed_break = not (auto_mode or max_mode)

        # First-chunk floor override. An empty rolling context marks
        # either the start of recording or the chunk right after a
        # context-reset silence — both cases where Whisper has no prior
        # text to bias on and benefits from a longer audio window for a
        # punctuated bootstrap transcript. Once the rolling context is
        # populated, fall back to the regular per-chunk floor.
        #
        # Gated additionally on stream_context_length > 0 so the Patient
        # profile (context_length=0 → context never populates → every
        # chunk would look "empty") falls back to the regular floor and
        # an explicit `--stream-chunk-min 0.5` keeps short utterances
        # committable. The override only makes sense when there *is* a
        # rolling context whose bootstrap we're trying to protect.
        #
        # Clamped to <= stream_chunk_max so it can never sit above the
        # force-cut threshold and deadlock the chunker (e.g. a user
        # setting first-chunk-min=20 with chunk-max=10).
        effective_chunk_min = (
            min(self.stream_first_chunk_min, self.stream_chunk_max)
            if (not self._streaming_context
                and self.stream_context_length > 0)
            else self.stream_chunk_min
        )

        # Silence decision delegated to the configured SilenceGate. In dB
        # mode `in_utterance` picks LOW vs HIGH threshold (hysteresis); in
        # silero mode it's ignored (silero handles onset/offset smoothing
        # via min_silence_duration_ms internally).
        in_utterance = bool(session.audio_buffer)
        if self.silence_gate.is_silent(audio_bytes, in_utterance=in_utterance):
            # Mark the start of this silence interval (byte-offset in ms,
            # measured against audio_buffer as it stood when speech last
            # ended). silence_start_ms persists across many silent frames
            # until speech resumes and closes the interval.
            if session.silence_start_ms is None:
                session.silence_start_ms = buffer_ms
            session.silence_buffer += audio_bytes
            # Cap trailing silence to a defensive floor. The only consumer
            # (the pre-roll path below) uses just the last 0.5s, but the
            # cap gives headroom for larger silence-break settings and any
            # future pre-roll change. Max-mode has no concrete break, so
            # fall back to the 5s floor. Without this cap a long pause
            # grows the buffer unboundedly (~2 KB/s at 16 kHz int16 mono
            # → 7 MB/h of silence). 5s caps at 160 KB.
            cap_s = max(5.0, silence_break if fixed_break else 0.0)
            max_silence_bytes = int(cap_s * self.samplerate) * 2
            if len(session.silence_buffer) > max_silence_bytes:
                session.silence_buffer = session.silence_buffer[-max_silence_bytes:]
            sil_dur = time.time() - session.last_sound_time

            if fixed_break:
                session.waiting = sil_dur >= silence_break
                # Commit on every detected silence pause. stream_chunk_max
                # is only the basis for the force-cut below; it's not a
                # floor for silence-cuts. session.reset() in the session
                # loop resets start_time on each commit, so `elapsed`
                # here always measures time since the last commit (or
                # start of recording).
                if session.waiting and buffer_ms >= effective_chunk_min * 1000:
                    raise SilenceDetected(
                        f"Cut at silence after {elapsed:.2f}s "
                        f"(silent {sil_dur:.2f}s)"
                    )
                # Long-pause escape hatch. When silence reaches the
                # context-reset threshold and we still haven't committed,
                # flush whatever is in the buffer as long as it clears
                # the lower stream_chunk_min floor (the Whisper-
                # hallucination protection). This catches short
                # utterances stranded below stream_first_chunk_min: the
                # user clearly stopped talking — don't lose what they
                # said waiting for a bootstrap window that's never
                # going to fill. Also clears the rolling context, since
                # a pause this long is the same topic-shift signal that
                # the speech-resumption path uses for its own reset.
                reset_threshold = (self.stream_context_reset_silence
                                   * silence_break)
                if (not math.isinf(reset_threshold)
                        and sil_dur >= reset_threshold
                        and buffer_ms >= self.stream_chunk_min * 1000):
                    if self._streaming_context:
                        self.log(
                            f"Clearing chunk context after {sil_dur:.2f}s pause"
                        )
                        self.clear_streaming_context()
                    raise SilenceDetected(
                        f"Cut at long silence after {elapsed:.2f}s "
                        f"(silent {sil_dur:.2f}s, "
                        f"below first-chunk floor)"
                    )
            else:
                # Auto and Max never silence-cut. Auto defers the cut
                # decision to the force-cut below (which picks the best
                # tracked interval); Max only ever force-cuts at chunk-max.
                session.waiting = False
        else:
            # Speech resumes. Close any pending silence interval and log
            # it for Auto mode's later best-silence search.
            sil_dur = time.time() - session.last_sound_time
            if session.silence_start_ms is not None:
                session.silence_intervals.append(
                    (session.silence_start_ms, sil_dur * 1000.0)
                )
                session.silence_start_ms = None

            # If the gap since the last sound was long, drop the rolling
            # prompt context — a new utterance is more likely to be
            # poisoned by stale context than helped by it. The previous
            # version also required audio_buffer to be empty to protect
            # mid-utterance pauses, but a single noise spike during the
            # pause was enough to fill audio_buffer with ~550 ms of
            # preroll+spike and block the reset, letting the stale prompt
            # bias every subsequent chunk. The mid-utterance case is
            # mild; the contamination case was severe.
            #
            # Auto / Max have no concrete silence-break to multiply
            # against, so the reset can't fire in those modes; the
            # internal multiplier value is preserved for when silence-
            # break returns to a concrete value.
            if fixed_break:
                reset_threshold = self.stream_context_reset_silence * silence_break
                if (self._streaming_context
                        and not math.isinf(reset_threshold)
                        and sil_dur >= reset_threshold):
                    self.log(f"Clearing chunk context after {sil_dur:.2f}s pause")
                    self.clear_streaming_context()
            session.last_sound_time = time.time()
            session.waiting = False
            silence_buffer_data = np.frombuffer(session.silence_buffer, dtype=np.int16)
            # Add 0.5s of trailing silence back so word boundaries aren't clipped.
            length_of_half_a_second = int(0.5 * self.samplerate)
            session.audio_buffer += silence_buffer_data[-length_of_half_a_second:].tobytes() + audio_bytes
            session.silence_buffer = b''

        if elapsed >= self.stream_chunk_max and buffer_ms >= effective_chunk_min * 1000:
            if auto_mode:
                # Best-silence-in-window: pick the longest tracked silence
                # whose start position leaves at least stream_chunk_min of
                # audio before the cut. The remainder (silence preroll
                # plus subsequent speech) carries over to the next chunk
                # via _pending_chunk_audio.
                min_start_ms = effective_chunk_min * 1000
                candidates = [(s, d) for (s, d) in session.silence_intervals
                              if s >= min_start_ms]
                if candidates:
                    best_start, best_dur = max(candidates, key=lambda x: x[1])
                    cut_bytes = int(best_start / 1000.0 * self.samplerate) * 2
                    self._pending_chunk_audio = session.audio_buffer[cut_bytes:]
                    session.audio_buffer = session.audio_buffer[:cut_bytes]
                    raise SilenceDetected(
                        f"Auto-cut at best silence "
                        f"(start={best_start:.0f}ms, dur={best_dur:.0f}ms, "
                        f"elapsed={elapsed:.2f}s)"
                    )
            raise SilenceDetected(
                f"Force-cut at chunk-max ({elapsed:.2f}s)"
            )

        return {"partial": f"{len(session.audio_buffer)} bytes received "
                           f"(duration: {elapsed:.2f} seconds)"}

    def compose_prompt(self, base_prompt):
        """Concatenate the user's static prompt with the rolling chunk-tail
        context. Returns None when both are empty so callers can keep the
        backend default. Tail is appended (chronological order) so the
        model sees: [static hints] then [most recent words said].
        """
        tail = self._streaming_context if self.pseudo_streaming else ""
        parts = [p for p in (base_prompt, tail) if p]
        if not parts:
            return None
        return " ".join(parts)

    def update_streaming_context(self, text):
        """Append the latest chunk's text to the rolling context and trim
        to the last `self.stream_context_length` characters. No-op in
        batch mode (no chunking → nothing to carry forward) or when the
        length cap is 0 (OFF — user disabled rolling context entirely).
        """
        if not self.pseudo_streaming or self.stream_context_length <= 0:
            return
        text = (text or "").strip()
        if not text:
            return
        combined = f"{self._streaming_context} {text}".strip() if self._streaming_context else text
        if len(combined) > self.stream_context_length:
            combined = combined[-self.stream_context_length:]
        self._streaming_context = combined

    def clear_streaming_context(self):
        self._streaming_context = ""

    def transcribe_audio(self, audio_data):
        raise NotImplementedError()

    def finalize(self):
        raise NotImplementedError()

    def transcribe(self, audio_path) -> str:
        """Implement the shared `STTBackend.transcribe(audio_path)` contract by
        loading the WAV at `audio_path` and delegating to `transcribe_audio`.
        Scribe itself drives transcription through `transcribe_realtime_audio`
        / `finalize`; this is the path bard-style consumers go through.
        """
        import soundfile as sf
        audio_data, _ = sf.read(str(Path(audio_path)), dtype="int16")
        result = self.transcribe_audio(audio_data.tobytes())
        if isinstance(result, dict):
            return result.get("text", "") or ""
        return str(result)


class AbstractStreamingTranscriber(AbstractTranscriber, StreamingSTTBackend):
    """Shared base for streaming transcribers in scribe.

    Inherits scribe's session/notify_error/log plumbing from
    `AbstractTranscriber` and the streaming protocol (`feed_audio`,
    `open_session`, `close_session`) from `StreamingSTTBackend`. The
    backward-compat `transcribe_realtime_audio` adapter is taken from
    `StreamingSTTBackend` (drains `feed_audio` and returns the last
    event), overriding `AbstractTranscriber`'s buffering version which
    only makes sense for batch backends.
    """

    def transcribe_realtime_audio(self, chunk=b""):
        return StreamingSTTBackend.transcribe_realtime_audio(self, chunk)


def get_vosk_model(model, download_root=None, url=None):
    """Load the Vosk recognizer"""
    import vosk
    vosk.SetLogLevel(-1)
    if download_root is None:
        download_root = VOSK_MODELS_FOLDER
    model_path = os.path.join(download_root, model)
    if not os.path.exists(model_path):
        if url is None:
            url = f"https://alphacephei.com/vosk/models/{model}.zip"
        download_model(url, download_root)
        assert os.path.exists(model_path)

    return vosk.Model(model_path)


def get_vosk_recognizer(model, samplerate=16000):
    import vosk
    return vosk.KaldiRecognizer(model, samplerate)
