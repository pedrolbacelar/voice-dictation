"""Keeps the last few recordings on disk so a bad transcription can be retried."""

from datetime import datetime
from pathlib import Path

from . import config

_PREFIX = "recording-"


def _sorted_recordings() -> list[Path]:
    """Saved recordings, oldest first (timestamped names sort chronologically)."""
    if not config.RECORDINGS_DIR.exists():
        return []
    return sorted(config.RECORDINGS_DIR.glob(f"{_PREFIX}*.wav"))


def save(wav_bytes: bytes) -> Path:
    """Write the recording, then prune to the newest KEEP_LAST_RECORDINGS.

    The new file is written (via a temp file + atomic rename) BEFORE anything is
    pruned, so a crash mid-write never costs the previous recording.
    """
    config.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = config.RECORDINGS_DIR / f"{_PREFIX}{stamp}.wav"
    tmp_path = path.with_suffix(".wav.tmp")
    tmp_path.write_bytes(wav_bytes)
    tmp_path.replace(path)

    for old in _sorted_recordings()[: -config.KEEP_LAST_RECORDINGS]:
        old.unlink(missing_ok=True)
    return path


def latest() -> bytes | None:
    """WAV bytes of the most recent recording, or None if there is none."""
    saved = _sorted_recordings()
    return saved[-1].read_bytes() if saved else None
