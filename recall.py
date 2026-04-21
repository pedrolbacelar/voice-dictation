"""Recall recent voice transcriptions from the database.

Usage:
    python recall.py          # show last 5, pick one to copy
    python recall.py -n 10    # show last 10
    python recall.py --last   # copy the most recent one directly
"""

import argparse
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "voice_dictation.db"

# ANSI colors
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_WHITE = "\033[37m"
_YELLOW = "\033[33m"
_DIM_WHITE = "\033[2;37m"


def _copy_to_clipboard(text: str) -> None:
    """Copy text to clipboard via PowerShell (no extra deps needed)."""
    subprocess.run(
        ["powershell", "-Command", "Set-Clipboard", "-Value", text],
        check=True,
        capture_output=True,
    )


def _format_timestamp(iso_ts: str) -> str:
    """Convert ISO timestamp to a friendly local format."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return iso_ts[:16]


def _preview(text: str, max_len: int = 80) -> str:
    """Truncate text for preview display."""
    line = text.replace("\n", " ").strip()
    return line[:max_len - 3] + "..." if len(line) > max_len else line


def fetch_recent(n: int = 5) -> list[dict]:
    if not DB_PATH.exists():
        print(f"  {_YELLOW}Database not found:{_RESET} {DB_PATH}")
        return []

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """
        SELECT id, timestamp, text, language, model, audio_duration_s
        FROM transcriptions
        ORDER BY id DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "text": r[2],
            "language": r[3],
            "model": r[4],
            "audio_duration_s": r[5],
        }
        for r in rows
    ]


def show_and_pick(entries: list[dict]) -> None:
    if not entries:
        print(f"  {_DIM}No transcriptions found.{_RESET}")
        return

    print()
    print(f"  {_CYAN}{_BOLD}Recent Transcriptions{_RESET}")
    print(f"  {_DIM_WHITE}{'─' * 60}{_RESET}")

    for i, e in enumerate(entries, 1):
        ts = _format_timestamp(e["timestamp"])
        dur = f"{e['audio_duration_s']:.0f}s"
        preview = _preview(e["text"])
        print(
            f"  {_BOLD}{i}{_RESET})  "
            f"{_DIM}{ts}{_RESET}  "
            f"{_DIM}{dur:>4}{_RESET}  "
            f"{_WHITE}{preview}{_RESET}"
        )

    print(f"  {_DIM_WHITE}{'─' * 60}{_RESET}")
    print()

    try:
        choice = input(f"  Pick a number (1-{len(entries)}) or Enter to quit: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    if not choice:
        return

    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(entries)):
            print(f"  {_YELLOW}Invalid choice.{_RESET}")
            return
    except ValueError:
        print(f"  {_YELLOW}Invalid choice.{_RESET}")
        return

    selected = entries[idx]
    print()
    print(f"  {_GREEN}{_BOLD}Full text:{_RESET}")
    print(f"  {_DIM_WHITE}{'─' * 60}{_RESET}")
    for line in selected["text"].splitlines():
        print(f"  {line}")
    print(f"  {_DIM_WHITE}{'─' * 60}{_RESET}")

    _copy_to_clipboard(selected["text"])
    print(f"  {_GREEN}Copied to clipboard.{_RESET}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Recall recent voice transcriptions")
    parser.add_argument("-n", type=int, default=5, help="Number of entries to show (default: 5)")
    parser.add_argument("--last", action="store_true", help="Copy the most recent transcription directly")
    args = parser.parse_args()

    entries = fetch_recent(args.n)

    if args.last:
        if not entries:
            print(f"  {_DIM}No transcriptions found.{_RESET}")
            return
        _copy_to_clipboard(entries[0]["text"])
        print(f"  {_GREEN}Copied last transcription to clipboard:{_RESET}")
        print(f"  {_preview(entries[0]['text'], 120)}")
        return

    show_and_pick(entries)


if __name__ == "__main__":
    main()
