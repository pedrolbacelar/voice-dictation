import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (two levels up from this file)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Audio
SAMPLE_RATE = 16_000  # 16kHz mono — optimal for Whisper models
CHANNELS = 1

# Transcription models (cycled via hotkey)
MODELS = ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"]

# Languages (toggled via hotkey)
LANGUAGES = ["en", "pt"]
LANGUAGE_LABELS = {"en": "English", "pt": "Português"}

# Hotkeys
HOTKEY_RECORD = "ctrl+shift+space"
HOTKEY_LANGUAGE = "ctrl+shift+l"
HOTKEY_MODEL = "ctrl+shift+m"
