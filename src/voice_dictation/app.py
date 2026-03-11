import threading
import winsound

import keyboard
import pystray
from PIL import Image, ImageDraw

from . import config
from .recorder import Recorder
from .transcriber import transcribe
from .injector import inject_text


class VoiceDictation:
    def __init__(self):
        self._recorder = Recorder()
        self._language_idx = 0
        self._model_idx = 0
        self._state = "idle"  # idle | recording | transcribing
        self._tray: pystray.Icon | None = None

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
        img = Image.new("RGBA", 64, (0, 0, 0, 0))
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

    def _on_toggle_record(self) -> None:
        if self._state == "transcribing":
            return  # ignore while transcribing

        if self._state == "idle":
            # Start recording
            self._state = "recording"
            self._update_icon()
            winsound.Beep(1000, 100)
            self._recorder.start()
        else:
            # Stop recording → transcribe
            winsound.Beep(600, 100)
            wav_bytes = self._recorder.stop()
            if not wav_bytes:
                self._state = "idle"
                self._update_icon()
                return

            self._state = "transcribing"
            self._update_icon()

            # Transcribe in background thread to keep UI responsive
            threading.Thread(
                target=self._do_transcribe,
                args=(wav_bytes,),
                daemon=True,
            ).start()

    def _do_transcribe(self, wav_bytes: bytes) -> None:
        try:
            text = transcribe(wav_bytes, self.language, self.model)
            if text.strip():
                inject_text(text)
        except Exception as e:
            print(f"Transcription error: {e}")
        finally:
            self._state = "idle"
            self._update_icon()

    def _on_toggle_language(self, *_args) -> None:
        self._language_idx = (self._language_idx + 1) % len(config.LANGUAGES)
        self._update_icon()
        self._refresh_menu()
        print(f"Language: {self.language_label}")

    def _on_toggle_model(self, *_args) -> None:
        self._model_idx = (self._model_idx + 1) % len(config.MODELS)
        self._update_icon()
        self._refresh_menu()
        print(f"Model: {self.model}")

    def _on_quit(self, *_args) -> None:
        if self._recorder.is_recording:
            self._recorder.stop()
        keyboard.unhook_all()
        if self._tray is not None:
            self._tray.stop()

    # --- Main loop ---

    def run(self) -> None:
        if not config.OPENAI_API_KEY:
            print("ERROR: OPENAI_API_KEY not set. Add it to .env in the repo root.")
            return

        # Register global hotkeys
        keyboard.add_hotkey(config.HOTKEY_RECORD, self._on_toggle_record, suppress=True)
        keyboard.add_hotkey(config.HOTKEY_LANGUAGE, self._on_toggle_language, suppress=True)
        keyboard.add_hotkey(config.HOTKEY_MODEL, self._on_toggle_model, suppress=True)

        print(f"Voice Dictation running — {self.language_label} | {self.model}")
        print(f"  Record:   {config.HOTKEY_RECORD}")
        print(f"  Language: {config.HOTKEY_LANGUAGE}")
        print(f"  Model:    {config.HOTKEY_MODEL}")

        # System tray (blocks on this thread)
        self._tray = pystray.Icon(
            name="voice-dictation",
            icon=self._icon_idle,
            title=self._build_tooltip(),
            menu=self._build_menu(),
        )
        self._tray.run()


def main():
    app = VoiceDictation()
    app.run()
