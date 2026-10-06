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
LANGUAGES = ["pt", "en"]
LANGUAGE_LABELS = {"en": "English", "pt": "Português"}

# Recording limits
MAX_RECORDING_SECONDS = 600  # 10 minutes — auto-stops to prevent runaway recordings

# Saved recordings (for HOTKEY_RETRY). Only the newest few are kept; older ones
# are deleted on each save, so the folder never grows.
RECORDINGS_DIR = _REPO_ROOT / "recordings"
KEEP_LAST_RECORDINGS = 2

# Hotkeys
HOTKEY_RECORD = "ctrl+shift+space"
HOTKEY_LANGUAGE = "ctrl+shift+l"
HOTKEY_MODEL = "ctrl+shift+m"
HOTKEY_RECALL = "ctrl+shift+r"
HOTKEY_RETRY = "ctrl+shift+t"  # re-send the last recording to the API

# Clipboard paste (see injector.py). The transcription is put on the clipboard,
# pasted with Ctrl+V, and the user's clipboard text is put back a moment later.
PASTE_SETTLE_SECONDS = 0.05  # between clipboard write and Ctrl+V, and between Ctrl+V and Enter
CLIPBOARD_OPEN_TIMEOUT_SECONDS = 0.5  # keep retrying OpenClipboard this long while another process holds it
CLIPBOARD_OPEN_RETRY_SECONDS = 0.01
CLIPBOARD_WRITE_ATTEMPTS = 3  # write + read-back verifications before giving up on the paste
# Electron/Chromium targets read the clipboard well after the Ctrl+V key event,
# later still when busy; restoring sooner than this pasted the user's old clipboard.
CLIPBOARD_RESTORE_DELAY_SECONDS = 1.5

# Double-tap window (seconds). A double tap of HOTKEY_RECORD — at the START or at
# the STOP of a recording — means "no Enter" (don't auto-submit). We wait this long
# on each single tap to rule out a second one, so larger = easier to double-tap but
# adds this much lag before a single tap takes effect (both starting and stopping).
DOUBLE_PRESS_SECONDS = 0.30

# Visual recording indicators (mirrored onto every connected monitor)
SHOW_RECORDING_BORDER = True  # pulsing red border around each screen
SHOW_RECORDING_WIDGET = True  # small "● REC" widget at each screen's top-right corner
