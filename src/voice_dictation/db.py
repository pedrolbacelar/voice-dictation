"""SQLite database for transcription history."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .transcriber import TranscriptionResult
from .logger import MODEL_COST_PER_MIN

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "voice_dictation.db"

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            text            TEXT    NOT NULL,
            language        TEXT    NOT NULL,
            model           TEXT    NOT NULL,
            audio_duration_s REAL   NOT NULL,
            latency_s       REAL   NOT NULL,
            input_tokens    INTEGER,
            output_tokens   INTEGER,
            total_tokens    INTEGER,
            estimated_cost  REAL   NOT NULL
        )
    """)
    conn.commit()


def log_transcription(result: TranscriptionResult) -> int:
    """Insert a transcription record. Returns the row id."""
    conn = _get_conn()
    cost_per_min = MODEL_COST_PER_MIN.get(result.model, 0.006)
    estimated_cost = result.audio_duration_s / 60.0 * cost_per_min

    cursor = conn.execute(
        """
        INSERT INTO transcriptions
            (timestamp, text, language, model, audio_duration_s, latency_s,
             input_tokens, output_tokens, total_tokens, estimated_cost)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            result.text,
            result.language,
            result.model,
            result.audio_duration_s,
            result.latency_s,
            result.input_tokens,
            result.output_tokens,
            result.total_tokens,
            estimated_cost,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_session_stats() -> dict:
    """Get aggregate stats for all transcriptions."""
    conn = _get_conn()
    row = conn.execute("""
        SELECT
            COUNT(*) as total_requests,
            COALESCE(SUM(audio_duration_s), 0) as total_audio_s,
            COALESCE(SUM(estimated_cost), 0) as total_cost,
            COALESCE(SUM(total_tokens), 0) as total_tokens
        FROM transcriptions
    """).fetchone()
    return {
        "total_requests": row[0],
        "total_audio_s": row[1],
        "total_cost": row[2],
        "total_tokens": row[3],
    }


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
