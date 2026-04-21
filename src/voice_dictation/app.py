import signal
import threading
import winsound

import keyboard
import pystray
from PIL import Image, ImageDraw

from . import config
from . import logger
from . import db
from . import media
from .recorder import Recorder
from .transcriber import transcribe
from .injector import inject_text


class VoiceDictation:
    def __init__(self):
        self._recorder = Recorder()
        self._language_idx = 0
        self._model_idx = 0
        self._state = "idle"  # idle | recording | transcribing
        self._paused_media = False
        self._tray: pystray.Icon | None = None
        self._stop_event = threading.Event()

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

        if self._state == "idle":
            self._state = "recording"
            self._update_icon()
            winsound.Beep(1000, 100)
            logger.recording_start()
            self._paused_media = media.pause_if_playing()
            self._recorder.start(on_max_reached=self._on_max_recording)
        else:
            winsound.Beep(600, 100)
            wav_bytes = self._recorder.stop()
            if not wav_bytes:
                self._state = "idle"
                self._update_icon()
                self._resume_media_if_paused()
                return

            audio_s = len(wav_bytes) / (config.SAMPLE_RATE * 2)  # 16-bit mono
            logger.recording_stop(audio_s)

            self._state = "transcribing"
            self._update_icon()

            threading.Thread(
                target=self._do_transcribe,
                args=(wav_bytes,),
                daemon=True,
            ).start()

    def _do_transcribe(self, wav_bytes: bytes) -> None:
        try:
            result = transcribe(wav_bytes, self.language, self.model)
            if result.text.strip():
                inject_text(result.text)

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
            self._state = "idle"
            self._update_icon()
            self._resume_media_if_paused()

    def _on_max_recording(self) -> None:
        """Called when recording hits the max duration limit."""
        if self._state != "recording":
            return
        logger.recording_max_reached(config.MAX_RECORDING_SECONDS)
        winsound.Beep(600, 100)
        winsound.Beep(600, 100)  # double beep to signal auto-stop
        wav_bytes = self._recorder.stop()
        if not wav_bytes:
            self._state = "idle"
            self._update_icon()
            self._resume_media_if_paused()
            return

        audio_s = len(wav_bytes) / (config.SAMPLE_RATE * 2)
        logger.recording_stop(audio_s)

        self._state = "transcribing"
        self._update_icon()

        threading.Thread(
            target=self._do_transcribe,
            args=(wav_bytes,),
            daemon=True,
        ).start()

    def _on_recall(self) -> None:
        """Re-paste the most recent transcription at the cursor."""
        if self._state != "idle":
            return
        recent = db.get_recent(1)
        if not recent:
            logger.recall_empty()
            return
        text = recent[0]["text"]
        inject_text(text)
        logger.recall_injected(text)

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
        if self._recorder.is_recording:
            self._recorder.stop()
        self._resume_media_if_paused()
        keyboard.unhook_all()
        if self._tray is not None:
            self._tray.stop()
        self._stop_event.set()

    # --- Main loop ---

    def run(self) -> None:
        if not config.OPENAI_API_KEY:
            print("ERROR: OPENAI_API_KEY not set. Add it to .env in the repo root.")
            return

        # Register global hotkeys
        keyboard.add_hotkey(config.HOTKEY_RECORD, self._on_toggle_record, suppress=True)
        keyboard.add_hotkey(config.HOTKEY_LANGUAGE, self._on_toggle_language, suppress=True)
        keyboard.add_hotkey(config.HOTKEY_MODEL, self._on_toggle_model, suppress=True)
        keyboard.add_hotkey(config.HOTKEY_RECALL, self._on_recall, suppress=True)

        logger.startup(
            language_label=self.language_label,
            model=self.model,
            hotkeys={
                "record": config.HOTKEY_RECORD,
                "language": config.HOTKEY_LANGUAGE,
                "model": config.HOTKEY_MODEL,
                "recall": config.HOTKEY_RECALL,
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

        # Main thread polls so Ctrl+C can interrupt (Windows limitation)
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=0.5)
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
