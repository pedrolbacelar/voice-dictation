import io
import time
import wave
from dataclasses import dataclass

from openai import OpenAI

from . import config


_client: OpenAI | None = None


@dataclass
class TranscriptionResult:
    text: str
    audio_duration_s: float
    latency_s: float
    model: str
    language: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _wav_duration(wav_bytes: bytes) -> float:
    """Get duration of WAV audio in seconds."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate if rate else 0.0


def _extract_tokens(usage) -> tuple[int | None, int | None, int | None]:
    """Extract token counts from the API usage object (if available)."""
    if usage is None:
        return None, None, None
    # gpt-4o-mini-transcribe / gpt-4o-transcribe return UsageTokens (type="tokens")
    if hasattr(usage, "total_tokens"):
        return usage.input_tokens, usage.output_tokens, usage.total_tokens
    # whisper-1 returns UsageDuration (type="duration") — no token info
    return None, None, None


def transcribe(wav_bytes: bytes, language: str, model: str) -> TranscriptionResult:
    """Send WAV audio to OpenAI transcription API and return result with metadata."""
    client = _get_client()
    audio_file = io.BytesIO(wav_bytes)
    audio_file.name = "recording.wav"
    audio_duration = _wav_duration(wav_bytes)

    t0 = time.perf_counter()
    response = client.audio.transcriptions.create(
        model=model,
        file=audio_file,
        language=language,
    )
    latency = time.perf_counter() - t0

    input_tokens, output_tokens, total_tokens = _extract_tokens(
        getattr(response, "usage", None)
    )

    return TranscriptionResult(
        text=response.text,
        audio_duration_s=audio_duration,
        latency_s=latency,
        model=model,
        language=language,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
