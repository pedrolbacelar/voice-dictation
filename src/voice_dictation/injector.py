import ctypes
import time

import keyboard


# Win32 clipboard constants
CF_UNICODETEXT = 13

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def _get_clipboard() -> str:
    """Read current clipboard text (Win32)."""
    user32.OpenClipboard(0)
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _set_clipboard(text: str) -> None:
    """Write text to clipboard (Win32)."""
    user32.OpenClipboard(0)
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
    finally:
        user32.CloseClipboard()


def inject_text(text: str) -> None:
    """Paste text at the current cursor position via clipboard."""
    # Save original clipboard
    try:
        original = _get_clipboard()
    except Exception:
        original = ""

    # Set transcribed text and paste
    _set_clipboard(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    time.sleep(0.05)

    # Restore original clipboard
    try:
        _set_clipboard(original)
    except Exception:
        pass
