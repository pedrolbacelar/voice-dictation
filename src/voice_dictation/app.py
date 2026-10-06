import signal
import threading
import winsound

import pystray
from PIL import Image, ImageDraw

from . import config
from . import logger
from . import db
from . import media
from . import recordings
from .hotkeys import HotkeyManager
from .overlay import RecordingOverlay
from .recorder import Recorder
from .transcriber import transcribe
from .injector import ClipboardError, inject_text


class VoiceDictation:
    def __init__(self):
        self._recorder = Recorder()
        self._overlay = RecordingOverlay()
        self._language_idx = 0
        self._model_idx = 0
        self._state = "idle"  # idle | recording | transcribing
        self._paused_media = False
        self._tray: pystray.Icon | None = None
        self._hotkeys: HotkeyManager | None = None
        self._stop_event = threading.Event()

        # Double-tap detection: a second HOTKEY_RECORD press within
        # config.DOUBLE_PRESS_SECONDS starts a recording that pastes WITHOUT Enter.
        self._record_lock = threading.Lock()
        self._start_timer: threading.Timer | None = None
        self._stop_timer: threading.Timer | None = None
        self._press_enter = True  # whether the current recording auto-sends (Enter)

        # Session stats
        self._total_requests = 0
        self._total_audio_s = 0.0
        self._total_cost = 0.0
        self._total_tokens = 0

    @property
    def language(self) -> str:
        return config.LANGUAGES[self._language_idx]

    @property
    def language_label(self) -> str:
        return config.LANGUAGE_LABELS[self.language]

    @property
    def model(self) -> str:
        return config.MODELS[self._model_idx]

    # --- Icon generation ---

    def _make_icon(self, color: str) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=color)
        return img

    @property
    def _icon_idle(self) -> Image.Image:
        return self._make_icon("#808080")

    @property
    def _icon_recording(self) -> Image.Image:
        return self._make_icon("#FF3333")

    @property
    def _icon_transcribing(self) -> Image.Image:
        return self._make_icon("#FFCC00")

    def _update_icon(self) -> None:
        if self._tray is None:
            return
        icons = {
            "idle": self._icon_idle,
            "recording": self._icon_recording,
            "transcribing": self._icon_transcribing,
        }
        self._tray.icon = icons[self._state]
        self._tray.title = self._build_tooltip()

    def _build_tooltip(self) -> str:
        state_label = {"idle": "Ready", "recording": "Recording...", "transcribing": "Transcribing..."}
        return f"Voice Dictation — {state_label[self._state]}\n{self.language_label} | {self.model}"

    # --- Tray menu ---

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(f"Language: {self.language_label}", self._on_toggle_language),
            pystray.MenuItem(f"Model: {self.model}", self._on_toggle_model),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

    def _refresh_menu(self) -> None:
        if self._tray is not None:
            self._tray.menu = self._build_menu()
            self._tray.update_menu()

    # --- Hotkey handlers ---

    def _resume_media_if_paused(self) -> None:
        if self._paused_media:
            media.resume()
            self._paused_media = False

    def _on_toggle_record(self) -> None:
        if self._state == "transcribing":
            return  # ignore while transcribing

        # Both phases debounce the press to tell a single tap from a double tap,
        # because a double tap ALWAYS means "no Enter" (don't auto-submit):
        #   - at START: single = normal (Enter), double = record without Enter
        #   - at STOP:  single = honor the start mode, double = force no Enter
        # A message is only sent (Enter) when there was no double tap at all.
        if self._state == "idle":
            with self._record_lock:
                if self._start_timer is not None:
                    self._start_timer.cancel()
                    self._start_timer = None
                    double = True
                else:
                    self._start_timer = threading.Timer(
                        config.DOUBLE_PRESS_SECONDS, self._begin_recording_single
                    )
                    self._start_timer.daemon = True
                    self._start_timer.start()
                    double = False
            if double:
                self._begin_recording(press_enter=False)

        elif self._state == "recording":
            with self._record_lock:
                if self._stop_timer is not None:
                    self._stop_timer.cancel()
                    self._stop_timer = None
                    double = True
                else:
                    self._stop_timer = threading.Timer(
                        config.DOUBLE_PRESS_SECONDS, self._stop_single
                    )
                    self._stop_timer.daemon = True
                    self._stop_timer.start()
                    double = False
            if double:
                self._stop_and_transcribe(force_no_enter=True)

    def _begin_recording_single(self) -> None:
        """Fired when the start-tap window elapses with no second tap."""
        with self._record_lock:
            self._start_timer = None
        self._begin_recording(press_enter=True)

    def _stop_single(self) -> None:
        """Fired when the stop-tap window elapses with no second tap."""
        with self._record_lock:
            self._stop_timer = None
        self._stop_and_transcribe(force_no_enter=False)

    def _begin_recording(self, press_enter: bool) -> None:
        with self._record_lock:
            if self._state != "idle":
                return
            self._state = "recording"
            self._press_enter = press_enter
        self._update_icon()
        winsound.Beep(1000, 100)
        if not press_enter:
            winsound.Beep(1400, 90)  # ascending second beep = no-Enter mode
        logger.recording_start(press_enter=press_enter)
        self._paused_media = media.pause_if_playing()
        self._recorder.start(on_max_reached=self._on_max_recording)
        self._overlay.show(no_enter=not press_enter)

    def _stop_and_transcribe(self, force_no_enter: bool = False) -> None:
        with self._record_lock:
            if self._state != "recording":
                return  # already being stopped (debounce / auto-stop race)
            self._state = "transcribing"
            override = force_no_enter and self._press_enter
            if force_no_enter:
                self._press_enter = False
        self._update_icon()
        winsound.Beep(600, 100)
        if override:
            winsound.Beep(400, 90)  # descending second beep = Enter suppressed
        self._finalize_recording()

    def _finalize_recording(self) -> None:
        """Stop the recorder and start transcription (state already 'transcribing')."""
        wav_bytes = self._recorder.stop()
        if not wav_bytes:
            self._overlay.hide()
            self._state = "idle"
            self._update_icon()
            self._resume_media_if_paused()
            return

        audio_s = len(wav_bytes) / (config.SAMPLE_RATE * 2)  # 16-bit mono
        logger.recording_stop(audio_s)

        # Save before calling the API, so even a failed request can be retried.
        try:
            recordings.save(wav_bytes)
        except OSError as e:
            logger.recording_save_error(e)

        self._overlay.show_transcribing()  # red REC widget -> yellow "transcribing"
        threading.Thread(
            target=self._do_transcribe,
            args=(wav_bytes,),
            daemon=True,
        ).start()

    def _do_transcribe(self, wav_bytes: bytes) -> None:
        try:
            result = transcribe(wav_bytes, self.language, self.model)
            if result.text.strip():
                try:
                    inject_text(result.text, press_enter=self._press_enter)
                except ClipboardError as e:
                    logger.paste_error(e)  # still logged below, so Ctrl+Shift+R can re-paste it

                # Log to terminal
                logger.transcription_result(
                    text=result.text,
                    model=result.model,
                    language=result.language,
                    audio_duration_s=result.audio_duration_s,
                    latency_s=result.latency_s,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    total_tokens=result.total_tokens,
                )

                # Log to database
                db.log_transcription(result)

                # Update session stats
                cost_per_min = logger.MODEL_COST_PER_MIN.get(result.model, 0.006)
                self._total_requests += 1
                self._total_audio_s += result.audio_duration_s
                self._total_cost += result.audio_duration_s / 60.0 * cost_per_min
                self._total_tokens += result.total_tokens or 0
            else:
                logger.transcription_empty()
        except Exception as e:
            logger.transcription_error(e)
        finally:
            self._overlay.hide()
            self._state = "idle"
            self._update_icon()
            self._resume_media_if_paused()

    def _on_max_recording(self) -> None:
        """Called when recording hits the max duration limit."""
        with self._record_lock:
            if self._state != "recording":
                return
            self._state = "transcribing"
        logger.recording_max_reached(config.MAX_RECORDING_SECONDS)
        winsound.Beep(600, 100)
        winsound.Beep(600, 100)  # double beep to signal auto-stop
        self._update_icon()
        self._finalize_recording()  # auto-stop keeps the mode chosen at start

    def _on_recall(self) -> None:
        """Re-paste the most recent transcription at the cursor."""
        if self._state != "idle":
            return
        recent = db.get_recent(1)
        if not recent:
            logger.recall_empty()
            return
        text = recent[0]["text"]
        try:
            inject_text(text)
        except ClipboardError as e:
            logger.paste_error(e)
            return
        logger.recall_injected(text)

    def _on_retry(self) -> None:
        """Re-send the last saved recording to the API (current model/language).

        The result is pasted WITHOUT Enter: a retry is a correction, so the text
        is left for review instead of auto-submitting.
        """
        with self._record_lock:
            if self._state != "idle":
                return
            wav_bytes = recordings.latest()
            if wav_bytes is None:
                logger.retry_empty()
                return
            self._state = "transcribing"
            self._press_enter = False
        self._update_icon()
        audio_s = len(wav_bytes) / (config.SAMPLE_RATE * 2)  # 16-bit mono
        logger.retry_start(audio_s, self.model)
        self._overlay.show_transcribing()
        threading.Thread(
            target=self._do_transcribe,
            args=(wav_bytes,),
            daemon=True,
        ).start()

    def _on_toggle_language(self, *_args) -> None:
        self._language_idx = (self._language_idx + 1) % len(config.LANGUAGES)
        self._update_icon()
        self._refresh_menu()
        logger.language_switch(self.language_label)

    def _on_toggle_model(self, *_args) -> None:
        self._model_idx = (self._model_idx + 1) % len(config.MODELS)
        self._update_icon()
        self._refresh_menu()
        logger.model_switch(self.model)

    def _on_quit(self, *_args) -> None:
        for timer in (self._start_timer, self._stop_timer):
            if timer is not None:
                timer.cancel()
        self._start_timer = None
        self._stop_timer = None
        if self._recorder.is_recording:
            self._recorder.stop()
        self._overlay.destroy()
        self._resume_media_if_paused()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        if self._tray is not None:
            self._tray.stop()
        self._stop_event.set()

    # --- Main loop ---

    def run(self) -> None:
        if not config.OPENAI_API_KEY:
            print("ERROR: OPENAI_API_KEY not set. Add it to .env in the repo root.")
            return

        # Register global hotkeys via Win32 RegisterHotKey (see hotkeys.py).
        self._hotkeys = HotkeyManager()
        self._hotkeys.register(config.HOTKEY_RECORD, self._on_toggle_record)
        self._hotkeys.register(config.HOTKEY_LANGUAGE, self._on_toggle_language)
        self._hotkeys.register(config.HOTKEY_MODEL, self._on_toggle_model)
        self._hotkeys.register(config.HOTKEY_RECALL, self._on_recall)
        self._hotkeys.register(config.HOTKEY_RETRY, self._on_retry)
        failures = self._hotkeys.start()
        for spec, err in failures:
            print(f"ERROR: failed to register hotkey {spec!r} (GetLastError={err}) — likely owned by another process")

        logger.startup(
            language_label=self.language_label,
            model=self.model,
            hotkeys={
                "record": config.HOTKEY_RECORD,
                "language": config.HOTKEY_LANGUAGE,
                "model": config.HOTKEY_MODEL,
                "recall": config.HOTKEY_RECALL,
                "retry": config.HOTKEY_RETRY,
                "quit": "ctrl+c",
            },
        )

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, lambda *_: self._on_quit())

        # Run tray in a background thread so main thread can catch Ctrl+C
        self._tray = pystray.Icon(
            name="voice-dictation",
            icon=self._icon_idle,
            title=self._build_tooltip(),
            menu=self._build_menu(),
        )
        tray_thread = threading.Thread(target=self._tray.run, daemon=True)
        tray_thread.start()

        # Main thread polls so Ctrl+C can interrupt (Windows limitation).
        # It also pumps the Tk overlay — Tk must be serviced on the thread
        # that created it (here, the main thread).
        try:
            while not self._stop_event.is_set():
                self._overlay.pump()
                self._stop_event.wait(timeout=0.05)
        except KeyboardInterrupt:
            self._on_quit()

        logger.session_summary(
            self._total_requests,
            self._total_audio_s,
            self._total_cost,
            self._total_tokens,
        )
        db.close()
        logger.shutdown()


def main():
    app = VoiceDictation()
    app.run()
