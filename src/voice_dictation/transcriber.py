import io

from openai import OpenAI

from . import config


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def transcribe(wav_bytes: bytes, language: str, model: str) -> str:
    """Send WAV audio to OpenAI transcription API and return the text."""
    client = _get_client()
    audio_file = io.BytesIO(wav_bytes)
    audio_file.name = "recording.wav"

    response = client.audio.transcriptions.create(
        model=model,
        file=audio_file,
        language=language,
    )
    return response.text
