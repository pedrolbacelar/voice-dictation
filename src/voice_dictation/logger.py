"""Colored terminal logging for voice dictation."""

from datetime import datetime

# ANSI color codes
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"
_WHITE = "\033[37m"
_DIM_WHITE = "\033[2;37m"

# Pricing per minute of audio (USD)
MODEL_COST_PER_MIN = {
    "gpt-4o-mini-transcribe": 0.003,
    "gpt-4o-transcribe": 0.006,
    "whisper-1": 0.006,
}


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _bar() -> str:
    return f"{_DIM_WHITE}|{_RESET}"


def startup(language_label: str, model: str, hotkeys: dict[str, str]) -> None:
    """Print styled startup banner."""
    print()
    print(f"  {_CYAN}{_BOLD}Voice Dictation{_RESET}")
    print(f"  {_DIM_WHITE}{'─' * 40}{_RESET}")
    print(f"  {_bar()} {_DIM}config{_RESET}   {language_label} {_DIM}•{_RESET} {model}")
    print(f"  {_bar()}")
    for action, key in hotkeys.items():
        print(f"  {_bar()} {_DIM}{action:>10}{_RESET}  {_WHITE}{key}{_RESET}")
    print(f"  {_DIM_WHITE}{'─' * 40}{_RESET}")
    print()


def recording_start() -> None:
    print(f"  {_DIM_WHITE}{_timestamp()}{_RESET}  {_RED}● rec{_RESET}", flush=True)


def recording_stop(duration_s: float) -> None:
    print(
        f"  {_DIM_WHITE}{_timestamp()}{_RESET}  {_YELLOW}■ stop{_RESET}"
        f"  {_DIM}{duration_s:.1f}s audio{_RESET}",
        flush=True,
    )


def transcription_result(
    text: str,
    model: str,
    language: str,
    audio_duration_s: float,
    latency_s: float,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    cost = audio_duration_s / 60.0 * MODEL_COST_PER_MIN.get(model, 0.006)
    preview = text.strip()
    if len(preview) > 120:
        preview = preview[:117] + "..."

    # Build the stats line
    parts = [f"{latency_s:.1f}s latency"]
    if total_tokens is not None:
        parts.append(f"{total_tokens} tok")
        if input_tokens is not None and output_tokens is not None:
            parts.append(f"({input_tokens}in/{output_tokens}out)")
    parts.append(f"${cost:.4f}")

    stats = f"  {_DIM}•{_RESET}  ".join(
        [f"{_DIM}{p}{_RESET}" for p in parts]
    )

    print(f"  {_DIM_WHITE}{_timestamp()}{_RESET}  {_GREEN}✓ done{_RESET}  {stats}")
    print(f"  {'':>10}  {_WHITE}{preview}{_RESET}")
    print(flush=True)


def transcription_empty() -> None:
    print(
        f"  {_DIM_WHITE}{_timestamp()}{_RESET}  {_DIM}  (empty transcription){_RESET}",
        flush=True,
    )


def transcription_error(error: Exception) -> None:
    print(
        f"  {_DIM_WHITE}{_timestamp()}{_RESET}  {_RED}✗ error{_RESET}"
        f"  {_DIM}{error}{_RESET}",
        flush=True,
    )


def language_switch(label: str) -> None:
    print(
        f"  {_DIM_WHITE}{_timestamp()}{_RESET}  {_CYAN}⇄ lang{_RESET}   {label}",
        flush=True,
    )


def model_switch(model: str) -> None:
    print(
        f"  {_DIM_WHITE}{_timestamp()}{_RESET}  {_MAGENTA}⇄ model{_RESET}  {model}",
        flush=True,
    )


def shutdown() -> None:
    print(f"\n  {_DIM}Voice Dictation stopped.{_RESET}\n")


def session_summary(total_requests: int, total_audio_s: float, total_cost: float, total_tokens: int) -> None:
    if total_requests == 0:
        return
    print(f"  {_DIM_WHITE}{'─' * 40}{_RESET}")
    parts = [
        f"{total_requests} requests",
        f"{total_audio_s:.0f}s audio",
    ]
    if total_tokens:
        parts.append(f"{total_tokens} tokens")
    parts.append(f"${total_cost:.4f}")
    print(f"  {_bar()} {_DIM}session{_RESET}  {' • '.join(parts)}")
    print(f"  {_DIM_WHITE}{'─' * 40}{_RESET}")
