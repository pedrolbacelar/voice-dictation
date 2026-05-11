from __future__ import annotations

import math
import queue
import time
import tkinter as tk
from typing import Optional

from . import config


_TRANSPARENT_KEY = "#010203"  # near-black placeholder mapped to transparent
_BORDER_COLOR = "#FF2222"
_BORDER_THICKNESS = 6  # px on each edge of the primary monitor
_WIDGET_BG = "#111111"
_WIDGET_FG = "#FFFFFF"
_PULSE_PERIOD_S = 1.4
_PULSE_ALPHA_MIN = 0.55
_PULSE_ALPHA_MAX = 1.0


class RecordingOverlay:
    """Pulsing red border + small 'REC' widget shown while audio is being recorded.

    The Tk root lives on the main thread (where this class is constructed).
    `show()` / `hide()` are safe to call from any thread — they push onto a
    queue that `pump()` drains from the main thread, alongside `root.update()`.
    """

    def __init__(self) -> None:
        self._cmd_q: queue.Queue[str] = queue.Queue()
        self._root: Optional[tk.Tk] = None
        self._border: Optional[tk.Toplevel] = None
        self._widget: Optional[tk.Toplevel] = None
        self._active = False
        self._pulse_started_at = 0.0
        self._enabled = config.SHOW_RECORDING_BORDER or config.SHOW_RECORDING_WIDGET
        if not self._enabled:
            return
        self._root = tk.Tk()
        self._root.withdraw()
        if config.SHOW_RECORDING_BORDER:
            self._build_border()
        if config.SHOW_RECORDING_WIDGET:
            self._build_widget()
        self._root.update_idletasks()

    # --- Public API (thread-safe) ---

    def show(self) -> None:
        if self._enabled:
            self._cmd_q.put("show")

    def hide(self) -> None:
        if self._enabled:
            self._cmd_q.put("hide")

    def pump(self) -> None:
        """Drain pending commands, tick the pulse, and process Tk events.
        Must be called from the thread that constructed this overlay.
        """
        if not self._enabled or self._root is None:
            return
        try:
            while True:
                cmd = self._cmd_q.get_nowait()
                if cmd == "show":
                    self._show_on_tk()
                elif cmd == "hide":
                    self._hide_on_tk()
        except queue.Empty:
            pass
        if self._active:
            self._tick_pulse()
        try:
            self._root.update()
        except tk.TclError:
            pass

    def destroy(self) -> None:
        if not self._enabled or self._root is None:
            return
        self._active = False
        try:
            self._root.destroy()
        except tk.TclError:
            pass
        self._root = None

    # --- Tk internals ---

    def _build_border(self) -> None:
        assert self._root is not None
        w = self._root.winfo_screenwidth()
        h = self._root.winfo_screenheight()
        top = tk.Toplevel(self._root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-transparentcolor", _TRANSPARENT_KEY)
        top.geometry(f"{w}x{h}+0+0")
        top.configure(bg=_TRANSPARENT_KEY)
        top.withdraw()
        canvas = tk.Canvas(
            top, width=w, height=h, bg=_TRANSPARENT_KEY, highlightthickness=0
        )
        canvas.pack(fill="both", expand=True)
        t = _BORDER_THICKNESS
        canvas.create_rectangle(0, 0, w, t, fill=_BORDER_COLOR, outline="")
        canvas.create_rectangle(0, h - t, w, h, fill=_BORDER_COLOR, outline="")
        canvas.create_rectangle(0, 0, t, h, fill=_BORDER_COLOR, outline="")
        canvas.create_rectangle(w - t, 0, w, h, fill=_BORDER_COLOR, outline="")
        self._border = top

    def _build_widget(self) -> None:
        assert self._root is not None
        w, h = 86, 28
        sw = self._root.winfo_screenwidth()
        x = sw - w - 20
        y = 20
        top = tk.Toplevel(self._root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=_WIDGET_BG)
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.withdraw()
        frame = tk.Frame(top, bg=_WIDGET_BG)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        dot = tk.Canvas(frame, width=12, height=12, bg=_WIDGET_BG, highlightthickness=0)
        dot.create_oval(1, 1, 11, 11, fill=_BORDER_COLOR, outline="")
        dot.pack(side="left")
        label = tk.Label(
            frame, text="REC", fg=_WIDGET_FG, bg=_WIDGET_BG,
            font=("Segoe UI", 10, "bold"),
        )
        label.pack(side="left", padx=(6, 0))
        self._widget = top

    def _show_on_tk(self) -> None:
        self._active = True
        self._pulse_started_at = time.monotonic()
        for win in (self._border, self._widget):
            if win is not None:
                win.deiconify()
                win.lift()
                win.attributes("-topmost", True)

    def _hide_on_tk(self) -> None:
        self._active = False
        for win in (self._border, self._widget):
            if win is not None:
                win.withdraw()

    def _tick_pulse(self) -> None:
        elapsed = time.monotonic() - self._pulse_started_at
        phase = (elapsed % _PULSE_PERIOD_S) / _PULSE_PERIOD_S
        eased = 0.5 - 0.5 * math.cos(phase * 2 * math.pi)
        alpha = _PULSE_ALPHA_MIN + (_PULSE_ALPHA_MAX - _PULSE_ALPHA_MIN) * eased
        for win in (self._border, self._widget):
            if win is not None:
                try:
                    win.attributes("-alpha", alpha)
                except tk.TclError:
                    pass
