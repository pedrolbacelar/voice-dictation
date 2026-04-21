from __future__ import annotations

import io
import threading
import wave
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from . import config


class Recorder:
    """Records audio from the default microphone into an in-memory WAV buffer."""

    def __init__(self):
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._timer: threading.Timer | None = None
        self._on_max_reached: Optional[Callable] = None

    @property
    def is_recording(self) -> bool:
        return self._stream is not None and self._stream.active

    def start(self, on_max_reached: Optional[Callable] = None) -> None:
        self._frames = []
        self._on_max_reached = on_max_reached
        self._stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

        # Auto-stop after MAX_RECORDING_SECONDS
        self._timer = threading.Timer(
            config.MAX_RECORDING_SECONDS,
            self._auto_stop,
        )
        self._timer.daemon = True
        self._timer.start()

    def _auto_stop(self) -> None:
        """Called when max recording time is reached."""
        if self.is_recording and self._on_max_reached:
            self._on_max_reached()

    def stop(self) -> bytes:
        """Stop recording and return WAV bytes."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return b""

        audio = np.concatenate(self._frames, axis=0)
        return self._to_wav(audio)

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        self._frames.append(indata.copy())

    def _to_wav(self, audio: np.ndarray) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(config.CHANNELS)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(config.SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return buf.getvalue()
