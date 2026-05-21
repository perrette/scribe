"""Unit tests for the whisper-futo text-layer post-processing.

pywhispercpp 1.4.1 advertises `suppress_non_speech_tokens` in its param
schema but the underlying C struct doesn't expose it. We filter at the
text layer instead — these tests pin both the regex behaviour and the
end-to-end `transcribe_audio` path (with a fake model) so a future
binding update doesn't accidentally remove the safety net.
"""
import numpy as np
import pytest

from scribe.backends.whisper_futo import (
    WhisperFutoTranscriber,
    _NON_SPEECH_WHOLE_RE,
    _NON_SPEECH_INLINE_RE,
    _PHONETIC_RE,
)


SR = 16000


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    """Stand-in for pywhispercpp.Model. Records kwargs for assertions."""
    def __init__(self, segments):
        self._segments = segments
        self.last_kwargs = None
        self.last_audio = None

    def transcribe(self, audio, **kwargs):
        self.last_audio = audio
        self.last_kwargs = kwargs
        return self._segments


def make_transcriber(*texts):
    """Build a WhisperFutoTranscriber wired to a FakeModel that returns
    the given segment texts. Passing model= bypasses the FUTO download."""
    model = FakeModel([FakeSegment(t) for t in texts])
    tr = WhisperFutoTranscriber("small", model=model)
    return tr, model


def audio_bytes_for_duration(duration_s):
    """Return raw int16 PCM bytes of the requested duration at 16 kHz."""
    return np.zeros(int(duration_s * SR), dtype=np.int16).tobytes()


# Regex layer ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "(music)",
    "[Applause]",
    "(keyboard clicking)",
    "*typing*",
    "  (Music) ",
    "(silence).",
    "[MUSIC PLAYING]",
])
def test_whole_chunk_regex_matches_sound_effect_annotations(text):
    assert _NON_SPEECH_WHOLE_RE.match(text)


@pytest.mark.parametrize("text", [
    "Bonjour comment ça va",
    "OK.",
    "",
    "(this is a much much much longer sentence wrapped in parens that probably is real speech)",
])
def test_whole_chunk_regex_preserves_normal_text(text):
    assert not _NON_SPEECH_WHOLE_RE.match(text)


@pytest.mark.parametrize("text,expected", [
    # User-reported regression cases (2026-05-22 chat):
    ("(keyboard typing)", ""),
    ("[door opens][door closes][clears throat]", ""),
    ("[Breathing][Breathing]", ""),
    ("[KNOCKING][KNOCKING]", ""),
    ("(footsteps)(footsteps) [sniffing][sniffing]", ""),
    ("[drums][drums]", ""),
    # Mid-sentence: strip the noise token, preserve the speech, no word collisions.
    ("Hello (typing) world", "Hello world"),
    ("Bonjour (typing) ça va", "Bonjour ça va"),
    # No-space-before-bracket case: must not glue adjacent words.
    ("hello(typing)world", "hello world"),
    # Normal speech with no noise token: untouched.
    ("Bonjour comment ça va", "Bonjour comment ça va"),
])
def test_inline_regex_strips_noise_tokens(text, expected):
    # Mirrors what transcribe_audio does after the segments are joined.
    import re
    stripped = _NON_SPEECH_INLINE_RE.sub(" ", text)
    collapsed = re.sub(r"\s+", " ", stripped).strip()
    assert collapsed == expected


@pytest.mark.parametrize("text", [
    "ʰᵃᵗᵗᵗᵗ",        # modifier letters
    "ʰello",          # leading modifier letter
    "broken �",  # replacement character
])
def test_phonetic_regex_detects_modifier_letters_and_replacement(text):
    assert _PHONETIC_RE.search(text)


@pytest.mark.parametrize("text", [
    "Bonjour",
    "café",          # accented Latin: keep
    "naïve",
    "中文",           # CJK: keep
    "",
])
def test_phonetic_regex_preserves_normal_unicode(text):
    assert not _PHONETIC_RE.search(text)


# transcribe_audio end-to-end ----------------------------------------------

@pytest.mark.parametrize("segment_text", [
    " (music)",
    "(keyboard typing)",
    "[door opens][door closes][clears throat]",
    "[Breathing][Breathing]",
    "[KNOCKING][KNOCKING]",
    "(footsteps)(footsteps) [sniffing][sniffing]",
    "[drums][drums]",
])
def test_transcribe_audio_drops_sound_effect_chunk(segment_text):
    tr, _ = make_transcriber(segment_text)
    out = tr.transcribe_audio(audio_bytes_for_duration(1.0))
    assert out == {"text": ""}


def test_transcribe_audio_drops_phonetic_garbage_chunk():
    tr, _ = make_transcriber("ʰᵃᵗᵗᵗᵗ�")
    out = tr.transcribe_audio(audio_bytes_for_duration(1.0))
    assert out == {"text": ""}


def test_transcribe_audio_preserves_normal_speech_with_trailing_space():
    tr, _ = make_transcriber(" Bonjour", " comment", " ça va")
    out = tr.transcribe_audio(audio_bytes_for_duration(2.0))
    # Trailing space lets the next chunk concatenate without word-collision.
    assert out == {"text": "Bonjour comment ça va "}


def test_transcribe_audio_strips_leading_whitespace_from_first_segment():
    # whisper.cpp doesn't guarantee a BPE leading space at a chunk boundary.
    tr, _ = make_transcriber("Hello", " world")
    out = tr.transcribe_audio(audio_bytes_for_duration(1.0))
    assert out == {"text": "Hello world "}


def test_transcribe_audio_empty_segments_returns_empty():
    tr, _ = make_transcriber("")
    out = tr.transcribe_audio(audio_bytes_for_duration(1.0))
    assert out == {"text": ""}


def test_transcribe_audio_chunks_concatenate_without_word_collision():
    """The trailing-space invariant: a downstream `chunk1 + chunk2`
    concatenation must not glue words together."""
    tr1, _ = make_transcriber("très petit")
    tr2, _ = make_transcriber("même en mode")
    chunk1 = tr1.transcribe_audio(audio_bytes_for_duration(1.0))["text"]
    chunk2 = tr2.transcribe_audio(audio_bytes_for_duration(1.0))["text"]
    assert (chunk1 + chunk2).strip() == "très petit même en mode"


# max_tokens cap -----------------------------------------------------------

@pytest.mark.parametrize("duration_s,expected", [
    (0.3, 12),    # floor (12·0.3 = 3.6 → would round to 3, floor kicks in)
    (1.0, 12),    # floor still wins (12·1.0 = 12 == floor)
    (2.0, 24),    # past the floor: 12 tokens/sec
    (5.0, 60),
    (30.0, 360),  # whisper.cpp's own ~224 ceiling takes over here
])
def test_max_tokens_scales_with_duration(duration_s, expected):
    tr, model = make_transcriber("ok")
    tr.transcribe_audio(audio_bytes_for_duration(duration_s))
    assert model.last_kwargs["max_tokens"] == expected


def test_audio_ctx_scales_with_duration():
    tr, model = make_transcriber("ok")
    tr.transcribe_audio(audio_bytes_for_duration(1.0))
    # 1s × 50 audio_ctx/sec = 50, well under the 1500 max and over the 8 min.
    assert model.last_kwargs["audio_ctx"] == 50


def test_audio_ctx_caps_at_30_seconds():
    tr, model = make_transcriber("ok")
    tr.transcribe_audio(audio_bytes_for_duration(60.0))
    assert model.last_kwargs["audio_ctx"] == 1500


def test_audio_ctx_has_minimum_floor():
    tr, model = make_transcriber("ok")
    tr.transcribe_audio(audio_bytes_for_duration(0.05))  # 0.05s × 50 = 2.5
    assert model.last_kwargs["audio_ctx"] >= 8
