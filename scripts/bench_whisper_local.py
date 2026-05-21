#!/usr/bin/env python3
"""
Benchmark local Whisper backends on the same audio sample.

Compares:
  1. faster-whisper small int8 (what scribe currently uses)
  2. whisper.cpp via pywhispercpp, baseline ggml small (no ACFT)
  3. whisper.cpp via pywhispercpp, FUTO ACFT small + dynamic audio_ctx

Usage:
    # Record 5 seconds from the default mic, then benchmark:
    python scripts/bench_whisper_local.py --record 5

    # Or use an existing 16kHz mono wav file:
    python scripts/bench_whisper_local.py --wav path/to/sample.wav

    # Point to specific ggml files (defaults look in ~/.cache/whisper-cpp/):
    python scripts/bench_whisper_local.py --wav sample.wav \\
        --ggml-baseline ~/.cache/whisper-cpp/ggml-small.bin \\
        --ggml-acft     ~/.cache/whisper-cpp/ggml-small-acft-q8_0.bin

Where to get the ggml files:
  - Baseline:  https://huggingface.co/ggerganov/whisper.cpp
  - FUTO ACFT: https://huggingface.co/futo-org/acft-whisper

Notes:
  - All audio is converted to 16 kHz mono float32 before timing.
  - The ACFT run sets audio_ctx = ceil(duration_s * 50). 1500 = full 30 s.
  - Each backend runs N times; the FIRST run is reported separately (cold,
    includes model load and any CUDA/MKL init); subsequent runs are warm.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np


def load_or_record(args) -> tuple[np.ndarray, float]:
    if args.wav:
        path = Path(args.wav)
        with wave.open(str(path), "rb") as w:
            if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
                sys.exit(f"need 16kHz mono int16 wav, got "
                         f"{w.getframerate()}Hz {w.getnchannels()}ch {w.getsampwidth()*8}bit")
            raw = w.readframes(w.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        import sounddevice as sd
        print(f"Recording {args.record}s from default mic... speak now.")
        rec = sd.rec(int(args.record * 16000), samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        audio = rec.flatten().astype(np.float32) / 32768.0
        out = Path("bench_sample.wav")
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes((audio * 32768.0).astype(np.int16).tobytes())
        print(f"Saved recording to {out}")
    return audio, len(audio) / 16000.0


def time_runs(label: str, fn, n: int) -> None:
    print(f"\n=== {label} ===")
    text = None
    for i in range(n):
        t0 = time.perf_counter()
        text = fn()
        dt = time.perf_counter() - t0
        tag = "cold" if i == 0 else f"warm {i}"
        print(f"  [{tag}] {dt:6.2f}s")
    if text is not None:
        print(f"  transcript: {text.strip()[:200]}")


def bench_faster_whisper(audio: np.ndarray, model_name: str, language: str | None, n: int) -> None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("\n[skip] faster-whisper not installed")
        return
    model = WhisperModel(model_name, compute_type="int8")

    def run():
        segments, _info = model.transcribe(
            audio, language=language, vad_filter=False, beam_size=1
        )
        return "".join(s.text for s in segments)

    time_runs(f"faster-whisper {model_name} (int8, beam=1, no VAD)", run, n)


def bench_whisper_cpp(audio: np.ndarray, ggml_path: Path | None, label: str,
                      language: str | None, n: int, audio_ctx: int | None = None) -> None:
    if ggml_path is None or not ggml_path.exists():
        print(f"\n[skip] {label}: ggml file not found at {ggml_path}")
        return
    try:
        from pywhispercpp.model import Model
    except ImportError:
        print(f"\n[skip] {label}: pywhispercpp not installed (pip install pywhispercpp)")
        return
    # n_threads=0 makes pywhispercpp 1.4.1 raise "std::vector larger than max_size"
    # at transcribe time, so pass an explicit count.
    model = Model(str(ggml_path), n_threads=os.cpu_count() or 4)

    def run():
        # whisper.cpp defaults to greedy decoding (equivalent to beam_size=1).
        # Valid params come from pywhispercpp.constants.PARAMS_SCHEMA.
        kwargs = {"language": language or "auto"}
        if audio_ctx is not None:
            kwargs["audio_ctx"] = audio_ctx
        segs = model.transcribe(audio, **kwargs)
        return "".join(s.text for s in segs)

    time_runs(label, run, n)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--wav", help="path to 16kHz mono int16 wav file")
    src.add_argument("--record", type=float, metavar="SECONDS", help="record from default mic")
    p.add_argument("--language", default=None, help="language code (e.g. en, fr); None = autodetect")
    p.add_argument("--fw-model", default="small", help="faster-whisper model name (default: small)")
    p.add_argument("--ggml-baseline", type=Path,
                   default=Path.home() / ".cache/whisper-cpp/ggml-small.bin",
                   help="baseline (non-ACFT) ggml model path")
    p.add_argument("--ggml-acft", type=Path,
                   default=Path.home() / ".cache/whisper-cpp/ggml-small-acft-q8_0.bin",
                   help="FUTO ACFT ggml model path")
    p.add_argument("--runs", type=int, default=3, help="runs per backend (first is cold)")
    args = p.parse_args()

    audio, duration_s = load_or_record(args)
    print(f"\nAudio: {duration_s:.2f}s, {len(audio)} samples")

    # ACFT audio_ctx: 30s → 1500 tokens; encoder convs subsample by 2.
    # ceil(duration * 50) covers the actual audio length, clamped to 1500.
    audio_ctx = min(1500, max(8, math.ceil(duration_s * 50)))
    print(f"ACFT audio_ctx = {audio_ctx}  (full 30s = 1500)")

    bench_faster_whisper(audio, args.fw_model, args.language, args.runs)
    bench_whisper_cpp(audio, args.ggml_baseline, "whisper.cpp baseline small (no audio_ctx)",
                      args.language, args.runs, audio_ctx=None)
    bench_whisper_cpp(audio, args.ggml_acft, f"whisper.cpp FUTO ACFT small (audio_ctx={audio_ctx})",
                      args.language, args.runs, audio_ctx=audio_ctx)


if __name__ == "__main__":
    main()
