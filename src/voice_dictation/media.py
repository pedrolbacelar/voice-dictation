"""Pause/resume media via Windows SMTC.

Talks to the System Media Transport Controls to query and control whichever
player currently owns the media session (Spotify, browser, etc.), so we can
pause only when something is actually playing — no blind media-key toggles.
"""
import asyncio

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlaybackStatus,
    )
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


async def _pause_if_playing_async() -> bool:
    manager = await _SessionManager.request_async()
    session = manager.get_current_session()
    if session is None:
        return False
    info = session.get_playback_info()
    if info.playback_status != _PlaybackStatus.PLAYING:
        return False
    await session.try_pause_async()
    return True


async def _resume_async() -> None:
    manager = await _SessionManager.request_async()
    session = manager.get_current_session()
    if session is None:
        return
    await session.try_play_async()


def pause_if_playing() -> bool:
    """Pause the active media session iff it's currently Playing.

    Returns True when a session was paused, so the caller can remember to
    resume it later. Returns False on no session, not-playing, missing
    winsdk, or any SMTC failure.
    """
    if not _AVAILABLE:
        return False
    try:
        return asyncio.run(_pause_if_playing_async())
    except Exception:
        return False


def resume() -> None:
    if not _AVAILABLE:
        return
    try:
        asyncio.run(_resume_async())
    except Exception:
        pass
