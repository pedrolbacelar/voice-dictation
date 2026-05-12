"""Global hotkey registration via Win32 RegisterHotKey.

Unlike low-level keyboard hooks (WH_KEYBOARD_LL), RegisterHotKey reserves the
key combination at the OS level: WM_HOTKEY is delivered to our message queue
before any focused window's accelerator sees the key. It is not subject to
LowLevelHooksTimeout, so a slow Python thread cannot cause the hotkey to leak
into other apps (e.g., Windows Terminal's Ctrl+Shift+Space new-tab dropdown).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from typing import Callable

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_VK_NAMED = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
_VK_NAMED.update({f"f{i}": 0x6F + i for i in range(1, 25)})  # F1..F24

_MOD_NAMED = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "alt": MOD_ALT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
    "super": MOD_WIN,
}

# Argtypes — required for correctness on 64-bit Python (defaults truncate pointers).
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, ctypes.c_uint, ctypes.c_uint]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.TranslateMessage.restype = wt.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t  # LRESULT
user32.PostThreadMessageW.argtypes = [wt.DWORD, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.GetLastError.restype = wt.DWORD


def _parse(spec: str) -> tuple[int, int]:
    """Parse 'ctrl+shift+space' into (modifiers, vk_code)."""
    mods = 0
    vk: int | None = None
    for raw in spec.split("+"):
        part = raw.strip().lower()
        if not part:
            continue
        if part in _MOD_NAMED:
            mods |= _MOD_NAMED[part]
        elif part in _VK_NAMED:
            vk = _VK_NAMED[part]
        elif len(part) == 1:
            vk = ord(part.upper())
        else:
            raise ValueError(f"unknown key {part!r} in hotkey {spec!r}")
    if vk is None:
        raise ValueError(f"hotkey {spec!r} has no trigger key")
    return mods, vk


class HotkeyManager:
    """Registers global hotkeys and dispatches their handlers on worker threads."""

    def __init__(self):
        self._registrations: list[tuple[str, int, int, int, Callable[[], None]]] = []
        self._next_id = 1
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._ready = threading.Event()
        self._failures: list[tuple[str, int]] = []

    def register(self, spec: str, handler: Callable[[], None]) -> None:
        """Queue a hotkey. Must be called before start()."""
        mods, vk = _parse(spec)
        hid = self._next_id
        self._next_id += 1
        self._registrations.append((spec, hid, mods, vk, handler))

    def start(self, timeout: float = 5.0) -> list[tuple[str, int]]:
        """Start the message-pump thread; returns list of (spec, GetLastError) for any failed registrations."""
        self._thread = threading.Thread(target=self._run, name="hotkey-pump", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=timeout)
        return list(self._failures)

    def stop(self) -> None:
        """Break the message loop and unregister all hotkeys."""
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()

        registered: list[int] = []
        handlers: dict[int, Callable[[], None]] = {}
        for spec, hid, mods, vk, handler in self._registrations:
            if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                registered.append(hid)
                handlers[hid] = handler
            else:
                self._failures.append((spec, kernel32.GetLastError()))

        self._ready.set()

        msg = wt.MSG()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):
                    break
                if msg.message == WM_HOTKEY:
                    handler = handlers.get(msg.wParam)
                    if handler is not None:
                        threading.Thread(target=handler, daemon=True).start()
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hid in registered:
                user32.UnregisterHotKey(None, hid)
