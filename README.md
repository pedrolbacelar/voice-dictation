# Voice Dictation

Voice-to-text dictation tool that types transcribed speech wherever your cursor is. Uses OpenAI's transcription API as a replacement for Windows' built-in Win+H.

## Setup

```bash
# Clone and install
cd voice-dictation
pip install -e .

# Add your OpenAI API key
cp .env.example .env
# Edit .env with your key
```

## Usage

```bash
voice-dictation
```

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+Space` | Start/stop recording |
| `Ctrl+Shift+L` | Switch language (English / Portugues) |
| `Ctrl+Shift+M` | Cycle model |
| `Ctrl+Shift+R` | Re-paste the last transcription |
| `Ctrl+Shift+T` | Retry: re-send the last recording to the API (current model/language), paste without Enter |
| `Ctrl+C` | Quit |

### Flow

1. Click wherever you want text to appear
2. Press `Ctrl+Shift+Space` (beep = recording)
3. Speak
4. Press `Ctrl+Shift+Space` again (beep = stopped)
5. Text is transcribed and pasted at your cursor

## Models

| Model | Cost/min | Notes |
|-------|----------|-------|
| `gpt-4o-mini-transcribe` | $0.003 | Default, fastest, cheapest |
| `gpt-4o-transcribe` | $0.006 | Best quality |
| `whisper-1` | $0.006 | Legacy |

## Terminal Output

The app logs each transcription with colored output:

- Recording start/stop indicators
- Transcription text preview
- Latency, token usage, and estimated cost per request
- Session summary on exit (total requests, audio, tokens, cost)

## Database

All transcriptions are logged to a local SQLite database (`voice_dictation.db` in the repo root, gitignored). Each record includes:

- Timestamp, transcribed text, language, model
- Audio duration, API latency
- Input/output/total tokens
- Estimated cost

## Saved recordings

Each recording is written to `recordings/` (gitignored) before the API call, so a
hallucinated or failed transcription can be retried with `Ctrl+Shift+T` without
speaking again. Only the last `KEEP_LAST_RECORDINGS` (2) are kept; older files are
deleted on every save, so the folder never grows.

## Clipboard

The transcription is put on the clipboard and pasted with `Ctrl+V`; the text that
was on the clipboard before is put back `CLIPBOARD_RESTORE_DELAY_SECONDS` (1.5 s)
later. The delay matters: Electron/Chromium apps read the clipboard well after the
key event, and restoring sooner made them paste the old clipboard. The write is
verified (read back) before `Ctrl+V` is sent, so a busy clipboard can never make
the paste land stale content; if you copy something during the delay, your copy
wins and nothing is put back. Non-text clipboard content (images, files) is not
preserved.

## Architecture

```mermaid
flowchart LR
    A[Hotkey Press] --> B[Recorder]
    B -->|WAV bytes| C[OpenAI API]
    C -->|text + tokens| D[Injector]
    D -->|Ctrl+V| E[Cursor Position]
    C -->|metadata| F[SQLite DB]
    C -->|metadata| G[Terminal Logger]
```

## Project Structure

```
src/voice_dictation/
  app.py          # Main app, hotkeys, system tray, lifecycle
  config.py       # Env vars, constants, hotkey bindings
  recorder.py     # Microphone capture (sounddevice, 16kHz mono)
  transcriber.py  # OpenAI API client, token extraction
  injector.py     # Clipboard + Ctrl+V text injection (Win32)
  logger.py       # Colored terminal output
  db.py           # SQLite logging
  recordings.py   # Last-N recordings on disk, for retry
```

## Requirements

- Python 3.11+
- Windows (uses Win32 APIs for clipboard and winsound)
- OpenAI API key
