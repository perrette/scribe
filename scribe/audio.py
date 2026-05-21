import queue

import numpy as np
import sounddevice as sd


def get_duration(audio_length_bytes, # bytes
                sampling_rate = 16000,  # Hz
                num_channels = 1,  # Mono
                sample_width = 2,  # 16-bit audio
                ):

    # Calculate the number of samples
    num_samples = audio_length_bytes / (num_channels * sample_width)

    # Calculate the duration in seconds
    duration_seconds = num_samples / sampling_rate

    return duration_seconds


class Microphone:
    def __init__(self,
            samplerate = 16000,  # Vosk models typically use a 16kHz sample rate
            channels = 1,  # Mono audio
            device = None,  # Default device
            dtype = 'int16',  # Vosk models typically use 16-bit audio
        ):
        self.q = queue.Queue()
        self.samplerate = samplerate
        self.channels = channels
        self.device = device
        self.dtype = dtype

    # Fonction callback pour traiter les morceaux audio
    def callback(self, indata, frames, time, status):
        if status:
            print(status)
        self.q.put(bytes(indata))
        # if frames > 1000:  # Ajustez cette valeur pour essayer différents morceaux de taille
    #     rec.AcceptWaveform(bytes(indata))


    def open_stream(self):
        self.q.queue.clear()
        return sd.InputStream(samplerate=self.samplerate, device=self.device,
                              channels=self.channels, callback=self.callback, dtype=self.dtype)

    def device_info(self):
        return sd.query_devices(self.device, 'input')

    def get_duraction(self, audio_length_bytes):
        return get_duration(audio_length_bytes, self.samplerate, self.channels, {'int16':2}[self.dtype])



def calculate_decibels(data_bytes):
    """
    Calculate the decibel level of integer-valued audio data.

    :param data_bytes: Audio data as a bytes object.
    :return: Decibel level of the audio data.
    """
    # Normalize the integer samples to the range [-1.0, 1.0]
    data = np.frombuffer(data_bytes, dtype=np.int16)
    normalized_data = data / 32768.0

    # Calculate the RMS value
    rms = np.sqrt(np.mean(np.square(normalized_data)))

    if rms == 0:
        return -np.inf

    # Convert RMS to decibels
    db = 20 * np.log10(rms)

    return db


class SilenceGate:
    """Per-chunk silence decision for the realtime pipeline.

    Two implementations: DbSilenceGate (volume-only, current behaviour) and
    SileroSilenceGate (silero-vad). They are NOT a polished common API yet —
    `in_utterance` is meaningful for dB (picks LOW/HIGH threshold) and ignored
    by silero (which handles onset/offset hysteresis natively). The shared
    surface exists so the two call sites in models.py and openai_realtime.py
    can switch modes uniformly; a real unification waits on field experience.

    Pre-roll: the base class keeps a small ring buffer of recent audio so
    streaming backends that drop silent chunks (e.g. openai_realtime) can
    recover the last ~300 ms of about-to-be-speech audio on a silent→speech
    transition. Pseudo-streaming backends carry their own silence_buffer
    and just ignore `consume_pre_roll()`. Subclasses override `_decide`
    instead of `is_silent` so the buffering happens uniformly here.
    """

    def __init__(self, *, samplerate: int = 16000, pre_roll_ms: int = 300):
        self._pre_roll_max_bytes = int(pre_roll_ms / 1000 * samplerate) * 2
        self._pre_roll_buffer = b""
        self._pending_pre_roll = b""
        self._prev_silent = True

    def is_silent(self, audio_bytes: bytes, *, in_utterance: bool) -> bool:
        silent = self._decide(audio_bytes, in_utterance=in_utterance)
        if self._pre_roll_max_bytes > 0:
            # Snapshot the ring buffer BEFORE appending the current chunk,
            # so consume_pre_roll() returns the *prior* silent audio that
            # callers can prepend to `audio_bytes`. Including audio_bytes
            # would double-send the chunk that triggered the transition.
            if self._prev_silent and not silent:
                self._pending_pre_roll = self._pre_roll_buffer
            self._pre_roll_buffer += audio_bytes
            if len(self._pre_roll_buffer) > self._pre_roll_max_bytes:
                self._pre_roll_buffer = self._pre_roll_buffer[-self._pre_roll_max_bytes:]
        self._prev_silent = silent
        return silent

    def consume_pre_roll(self) -> bytes:
        """Pop the pre-roll bytes captured on the most recent silent →
        speech transition, or empty bytes when none is pending. One-shot:
        a second call returns empty until the next transition fires.

        Streaming backends that gate silence (openai_realtime) prepend
        this to the speech chunk so the first phoneme isn't clipped while
        silero confirms the onset.
        """
        buf, self._pending_pre_roll = self._pending_pre_roll, b""
        return buf

    def _decide(self, audio_bytes: bytes, *, in_utterance: bool) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        self._pre_roll_buffer = b""
        self._pending_pre_roll = b""
        self._prev_silent = True


class DbSilenceGate(SilenceGate):
    """Single-threshold volume-based silence detection.

    Kept as a no-dependency fallback for installs without onnxruntime —
    silero is the recommended path. dB has fundamental limits (any
    sub-threshold speech reads as silence) that no amount of threshold
    tuning fixes, so we don't expose more knobs than the bare minimum.

    `in_utterance` is accepted for API parity with SileroSilenceGate and
    ignored — the old onset/sustain hysteresis was a hack to compensate
    for dB's noise-rejection limits; silero replaces it properly.
    """

    def __init__(self, silence_thresh: float = -40.0, *,
                 samplerate: int = 16000, pre_roll_ms: int = 300):
        super().__init__(samplerate=samplerate, pre_roll_ms=pre_roll_ms)
        self.silence_thresh = silence_thresh

    def _decide(self, audio_bytes, *, in_utterance):
        return calculate_decibels(audio_bytes) < self.silence_thresh


def _bundled_silero_onnx_path():
    """Locate the bundled silero VAD ONNX model shipped under scribe_data.

    Uses the same `scribe_data.__file__` lookup pattern as the tray-icon
    loader in scribe/app.py — keeps the data discovery consistent and
    works whether the package is installed or run from a source checkout.
    """
    from pathlib import Path
    import scribe_data
    return Path(scribe_data.__file__).parent / "silero_vad.onnx"


class _SileroOnnxModel:
    """Thin port of silero-vad's OnnxWrapper, numpy-only.

    Runs the bundled silero VAD ONNX through onnxruntime. The model is
    stateful — it takes (audio_window, state, sr), returns
    (speech_prob, new_state). State is carried across calls; `_context`
    is the trailing 64 samples of the previous window (silero v5
    requires this for the 1024-sample receptive field).

    The state/context/sr protocol mirrors the reference implementation
    in silero_vad/utils_vad.py byte for byte — we just drop the torch
    wrappers and use numpy directly.
    """

    _CONTEXT_SIZE = 64  # 16 kHz only; would be 32 at 8 kHz

    def __init__(self, model_path: str):
        import onnxruntime
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )
        self._sr_array = np.array(16000, dtype=np.int64)
        self.reset_states()

    def reset_states(self, batch_size: int = 1):
        self._state = np.zeros((2, batch_size, 128), dtype=np.float32)
        self._context = np.zeros((batch_size, self._CONTEXT_SIZE), dtype=np.float32)
        self._initialised_context = False

    def __call__(self, window: np.ndarray) -> float:
        """Run one 512-sample window (float32, shape (512,)) and return speech prob."""
        x = window.reshape(1, -1).astype(np.float32, copy=False)
        if not self._initialised_context:
            self._context = np.zeros((x.shape[0], self._CONTEXT_SIZE), dtype=np.float32)
            self._initialised_context = True
        x_with_context = np.concatenate([self._context, x], axis=1)
        outs = self._session.run(
            None,
            {
                "input": x_with_context,
                "state": self._state,
                "sr": self._sr_array,
            },
        )
        prob, new_state = outs
        self._state = new_state
        self._context = x_with_context[:, -self._CONTEXT_SIZE:]
        return float(prob.item())


class _SileroVADIterator:
    """Pure-Python port of silero_vad.VADIterator's state machine.

    Same `triggered` / `temp_end` / `current_sample` semantics, same
    speech_start/speech_end event shape ({"start": int} / {"end": int}
    in sample units). Drops the torch wrapper around the model call —
    `_SileroOnnxModel` takes a numpy array directly.
    """

    def __init__(self, model: _SileroOnnxModel, *, threshold: float,
                 sampling_rate: int, min_silence_duration_ms: int,
                 speech_pad_ms: int):
        self.model = model
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_silence_samples = sampling_rate * min_silence_duration_ms / 1000
        self.speech_pad_samples = sampling_rate * speech_pad_ms / 1000
        self.reset_states()

    def reset_states(self):
        self.model.reset_states()
        self.triggered = False
        self.temp_end = 0
        self.current_sample = 0

    def __call__(self, window: np.ndarray):
        window_size_samples = window.shape[-1]
        self.current_sample += window_size_samples

        speech_prob = self.model(window)

        if (speech_prob >= self.threshold) and self.temp_end:
            self.temp_end = 0

        if (speech_prob >= self.threshold) and not self.triggered:
            self.triggered = True
            speech_start = max(
                0, self.current_sample - self.speech_pad_samples - window_size_samples
            )
            return {"start": int(speech_start)}

        if (speech_prob < self.threshold - 0.15) and self.triggered:
            if not self.temp_end:
                self.temp_end = self.current_sample
            if self.current_sample - self.temp_end < self.min_silence_samples:
                return None
            speech_end = self.temp_end + self.speech_pad_samples - window_size_samples
            self.temp_end = 0
            self.triggered = False
            return {"end": int(speech_end)}

        return None


class SileroSilenceGate(SilenceGate):
    """Voice-activity-based silence detection backed by the silero VAD model.

    Runs the bundled `silero_vad.onnx` (~2 MB) via `onnxruntime` — same
    model, same algorithm, same parameters as the upstream silero-vad
    package, but without pulling in torch (~1.6 GB). The `[vad]` extra
    installs only onnxruntime.

    Around the ONNX model + state machine we only do two things: a
    rechunker buffer (the model needs exactly 512-sample windows at
    16 kHz, sounddevice gives variable sizes), and a tiny state machine
    that flips `_in_speech` based on the iterator's speech_start /
    speech_end events.

    `in_utterance` is ignored; silero's own onset/offset smoothing
    (`min_silence_duration_ms`) replaces the dB gate's two-threshold
    trick.
    """

    _WINDOW_SAMPLES = 512  # silero v5 requirement at 16 kHz

    def __init__(self, *, sampling_rate: int = 16000, threshold: float = 0.5,
                 min_silence_ms: int = 300, speech_pad_ms: int = 30,
                 pre_roll_ms: int = 300):
        if sampling_rate != 16000:
            raise ValueError(
                f"SileroSilenceGate requires sampling_rate=16000 (got {sampling_rate})"
            )
        super().__init__(samplerate=sampling_rate, pre_roll_ms=pre_roll_ms)
        try:
            import onnxruntime  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is not installed. Install with: "
                "pip install 'scribe-cli[vad]' (or: pip install onnxruntime)"
            ) from exc
        model_path = _bundled_silero_onnx_path()
        if not model_path.exists():
            raise FileNotFoundError(
                f"Bundled silero VAD model not found at {model_path}. "
                "The scribe-cli install is broken — reinstall scribe-cli."
            )
        self._model = _SileroOnnxModel(str(model_path))
        self._iterator = _SileroVADIterator(
            self._model,
            threshold=threshold,
            sampling_rate=sampling_rate,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._buf: np.ndarray = np.zeros(0, dtype=np.int16)
        self._in_speech = False

    def _decide(self, audio_bytes, *, in_utterance):
        if audio_bytes:
            samples = np.frombuffer(audio_bytes, dtype=np.int16)
            self._buf = np.concatenate([self._buf, samples])
        while self._buf.size >= self._WINDOW_SAMPLES:
            window = self._buf[:self._WINDOW_SAMPLES]
            self._buf = self._buf[self._WINDOW_SAMPLES:]
            x = window.astype(np.float32) / 32768.0
            event = self._iterator(x)
            if event:
                if "start" in event:
                    self._in_speech = True
                elif "end" in event:
                    self._in_speech = False
        return not self._in_speech

    def reset(self):
        super().reset()
        self._iterator.reset_states()
        self._buf = np.zeros(0, dtype=np.int16)
        self._in_speech = False


def make_silence_gate(
    mode: str = "db",
    *,
    samplerate: int = 16000,
    silence_thresh: float = -40.0,
    vad_threshold: float = 0.5,
    vad_min_silence_ms: int = 300,
    vad_speech_pad_ms: int = 30,
) -> SilenceGate:
    """Build a SilenceGate from config. `mode` is "db" or "silero"."""
    if mode == "db":
        return DbSilenceGate(silence_thresh=silence_thresh)
    if mode == "silero":
        return SileroSilenceGate(
            sampling_rate=samplerate,
            threshold=vad_threshold,
            min_silence_ms=vad_min_silence_ms,
            speech_pad_ms=vad_speech_pad_ms,
        )
    raise ValueError(f"Unknown vad_mode: {mode!r} (expected 'db' or 'silero')")