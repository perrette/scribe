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
    """

    def is_silent(self, audio_bytes: bytes, *, in_utterance: bool) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        pass


class DbSilenceGate(SilenceGate):
    """Volume-only silence detection with two-threshold hysteresis.

    `in_utterance=True`  → silence_thresh        (LOW, permissive — soft
                                                  trailing syllables stay
                                                  classified as speech).
    `in_utterance=False` → silence_thresh_onset  (HIGH, strict — ambient
                                                  noise doesn't kick off a
                                                  chunk).

    When the two thresholds are equal the hysteresis collapses to a single
    floor (the existing batch-mode behaviour).
    """

    def __init__(self, silence_thresh: float = -40.0,
                 silence_thresh_onset: float = -25.0):
        self.silence_thresh = silence_thresh
        self.silence_thresh_onset = silence_thresh_onset

    def is_silent(self, audio_bytes, *, in_utterance):
        thresh = self.silence_thresh if in_utterance else self.silence_thresh_onset
        return calculate_decibels(audio_bytes) < thresh


class SileroSilenceGate(SilenceGate):
    """Voice-activity-based silence detection backed by silero-vad.

    Owns a silero_vad.VADIterator that does all the actual work — per-frame
    speech probability against `threshold`, plus `min_silence_duration_ms`
    smoothing to debounce speech-end events. Around it we only do two
    things: a rechunker buffer (silero needs exactly 512-sample windows at
    16 kHz, sounddevice gives variable sizes), and a tiny state machine
    that flips `_in_speech` based on the iterator's speech_start/speech_end
    events.

    `in_utterance` is ignored; silero's own onset/offset smoothing replaces
    the dB gate's two-threshold trick.
    """

    _WINDOW_SAMPLES = 512  # silero v5 requirement at 16 kHz

    def __init__(self, *, sampling_rate: int = 16000, threshold: float = 0.5,
                 min_silence_ms: int = 300, speech_pad_ms: int = 30):
        if sampling_rate != 16000:
            raise ValueError(
                f"SileroSilenceGate requires sampling_rate=16000 (got {sampling_rate})"
            )
        try:
            import torch
            from silero_vad import load_silero_vad, VADIterator
        except ImportError as exc:
            raise ImportError(
                "silero-vad is not installed. Install with: "
                "pip install 'scribe-cli[vad]' (or: pip install silero-vad)"
            ) from exc
        self._torch = torch
        self._model = load_silero_vad(onnx=True)
        self._iterator = VADIterator(
            self._model,
            threshold=threshold,
            sampling_rate=sampling_rate,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._buf: np.ndarray = np.zeros(0, dtype=np.int16)
        self._in_speech = False

    def is_silent(self, audio_bytes, *, in_utterance):
        if audio_bytes:
            samples = np.frombuffer(audio_bytes, dtype=np.int16)
            self._buf = np.concatenate([self._buf, samples])
        while self._buf.size >= self._WINDOW_SAMPLES:
            window = self._buf[:self._WINDOW_SAMPLES]
            self._buf = self._buf[self._WINDOW_SAMPLES:]
            x = self._torch.from_numpy(window.astype(np.float32) / 32768.0)
            event = self._iterator(x)
            if event:
                if "start" in event:
                    self._in_speech = True
                elif "end" in event:
                    self._in_speech = False
        return not self._in_speech

    def reset(self):
        self._iterator.reset_states()
        self._buf = np.zeros(0, dtype=np.int16)
        self._in_speech = False


def make_silence_gate(
    mode: str = "db",
    *,
    samplerate: int = 16000,
    silence_thresh: float = -40.0,
    silence_thresh_onset: float = -25.0,
    vad_threshold: float = 0.5,
    vad_min_silence_ms: int = 300,
    vad_speech_pad_ms: int = 30,
) -> SilenceGate:
    """Build a SilenceGate from config. `mode` is "db" or "silero"."""
    if mode == "db":
        return DbSilenceGate(silence_thresh=silence_thresh,
                             silence_thresh_onset=silence_thresh_onset)
    if mode == "silero":
        return SileroSilenceGate(
            sampling_rate=samplerate,
            threshold=vad_threshold,
            min_silence_ms=vad_min_silence_ms,
            speech_pad_ms=vad_speech_pad_ms,
        )
    raise ValueError(f"Unknown vad_mode: {mode!r} (expected 'db' or 'silero')")