"""Paste text at the cursor through the clipboard (Win32).

The paste is a synthetic Ctrl+V, so the target application reads the clipboard
on its own schedule: an Electron/Chromium app does it several IPC hops after
the key event, later still when it is busy. Two things used to make such a
paste land the user's OLD clipboard instead of the transcription:

1. ``OpenClipboard`` fails whenever another process holds the clipboard open
   (the clipboard-history service reads it after every change; the target app
   holds it while pasting). The write was never checked, so a failed write left
   the old content in place and Ctrl+V pasted that.
2. The original clipboard was put back a fixed 50 ms after Ctrl+V. A target
   that read the clipboard later than that got the restored original.

Now every clipboard open is retried while it is busy, the write is verified by
reading it back before Ctrl+V is sent, and the user's text is restored on a
timer well after the paste. A paste that arrives while a restore is pending
cancels it and carries the same user text forward, so our own text is never
mistaken for the user's; and if the user copied something else meanwhile, the
restore is skipped so their copy wins.
"""

import ctypes
import ctypes.wintypes as wt
import threading
import time

import keyboard

from . import config
from . import logger

# Win32 clipboard constants
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# use_last_error so ctypes.get_last_error() reports the failing call's error code
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Properly type Win32 functions for 64-bit Python
# Without this, ctypes defaults to c_int (32-bit) and truncates 64-bit pointers → crash
user32.OpenClipboard.argtypes = [wt.HWND]
user32.OpenClipboard.restype = wt.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wt.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wt.BOOL
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE

kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HANDLE
kernel32.GlobalLock.argtypes = [wt.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HANDLE]
kernel32.GlobalUnlock.restype = wt.BOOL
kernel32.GlobalFree.argtypes = [wt.HANDLE]
kernel32.GlobalFree.restype = wt.HANDLE


class ClipboardError(RuntimeError):
    """The clipboard could not be opened or written, or did not hold what was written."""


def _win32_error(what: str) -> ClipboardError:
    return ClipboardError(f"{what} failed (GetLastError={ctypes.get_last_error()})")


class _OpenClipboard:
    """Context manager that opens the clipboard, retrying while another process holds it."""

    def __enter__(self) -> "_OpenClipboard":
        deadline = time.monotonic() + config.CLIPBOARD_OPEN_TIMEOUT_SECONDS
        while not user32.OpenClipboard(None):
            if time.monotonic() >= deadline:
                raise _win32_error("OpenClipboard")
            time.sleep(config.CLIPBOARD_OPEN_RETRY_SECONDS)
        return self

    def __exit__(self, *_exc) -> None:
        user32.CloseClipboard()


def _read_text() -> str | None:
    """Clipboard text, or None when the clipboard holds no text (empty, image, files...)."""
    with _OpenClipboard():
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)


def _write_text(text: str) -> None:
    """Replace the clipboard content with text. Raises ClipboardError on any failure."""
    data = text.encode("utf-16-le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise _win32_error("GlobalAlloc")
    try:
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            raise _win32_error("GlobalLock")
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        with _OpenClipboard():
            if not user32.EmptyClipboard():
                raise _win32_error("EmptyClipboard")
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                raise _win32_error("SetClipboardData")
    except ClipboardError:
        kernel32.GlobalFree(handle)  # the system only takes ownership on success
        raise


def _write_text_verified(text: str) -> None:
    """Write text and read it back, retrying a few times, so Ctrl+V can only paste it."""
    last_error: ClipboardError | None = None
    for attempt in range(config.CLIPBOARD_WRITE_ATTEMPTS):
        if attempt:
            time.sleep(config.CLIPBOARD_OPEN_RETRY_SECONDS)
        try:
            _write_text(text)
            if _read_text() == text:
                return
            last_error = ClipboardError("clipboard content differs from what was written")
        except ClipboardError as e:
            last_error = e
    assert last_error is not None
    raise last_error


# One paste at a time. The user's clipboard text is put back later, on a timer;
# these hold what is on the clipboard meanwhile (our text) and what to put back.
_lock = threading.Lock()
_restore_timer: threading.Timer | None = None
_pasted_text: str | None = None  # our text, on the clipboard while a restore is pending
_user_text: str | None = None  # the user's text to put back (None: there was no text)


def _take_user_text() -> str | None:
    """Capture the user's clipboard text, which the paste is about to replace.

    While a restore from a previous paste is still pending, the clipboard holds
    OUR text, so the user's text captured back then is carried forward — unless
    the clipboard changed meanwhile: then the user copied something new, and
    that is what must come back. Caller holds _lock.
    """
    global _restore_timer, _pasted_text, _user_text
    try:
        current = _read_text()
    except ClipboardError:
        current = None  # unreadable now: nothing to put back; the write below still retries
    if _restore_timer is None:
        return current
    _restore_timer.cancel()
    _restore_timer = None
    carried = _user_text if current == _pasted_text else current
    _pasted_text = _user_text = None
    return carried


def _schedule_restore(user_text: str | None, pasted_text: str) -> None:
    """Caller holds _lock."""
    global _restore_timer, _pasted_text, _user_text
    _pasted_text, _user_text = pasted_text, user_text
    _restore_timer = threading.Timer(config.CLIPBOARD_RESTORE_DELAY_SECONDS, _restore)
    _restore_timer.daemon = True
    _restore_timer.start()


def _restore() -> None:
    """Put the user's text back, unless the clipboard changed since the paste (theirs wins)."""
    global _restore_timer, _pasted_text, _user_text
    with _lock:
        if _restore_timer is not threading.current_thread():
            return  # superseded by a newer paste while waiting for the lock
        pasted, user = _pasted_text, _user_text
        _restore_timer = _pasted_text = _user_text = None
        try:
            if user is None or _read_text() != pasted:
                return  # nothing to put back, or the user copied since: theirs wins
            _write_text(user)
        except ClipboardError as e:
            logger.clipboard_restore_error(e)


def inject_text(text: str, press_enter: bool = False) -> None:
    """Paste text at the current cursor position via clipboard.

    If press_enter is True, send Enter after the paste settles — useful for
    chat-style inputs where the user wants to submit immediately.

    Raises ClipboardError when the clipboard could not be made to hold the text;
    nothing is sent then, so the old clipboard content is never pasted.
    """
    with _lock:
        user_text = _take_user_text()
        _write_text_verified(text)
        time.sleep(config.PASTE_SETTLE_SECONDS)
        keyboard.send("ctrl+v")
        time.sleep(config.PASTE_SETTLE_SECONDS)
        if press_enter:
            keyboard.send("enter")
        _schedule_restore(user_text, text)
