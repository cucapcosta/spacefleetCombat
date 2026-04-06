"""ANSI colour helpers for the CLI layer."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Raw ANSI codes
# ---------------------------------------------------------------------------


class C:
    """Namespace for ANSI escape sequences."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def colored(text: str, color: str) -> str:
    return f"{color}{text}{C.RESET}"


def bold(text: str) -> str:
    return f"{C.BOLD}{text}{C.RESET}"


def dim(text: str) -> str:
    return f"{C.DIM}{text}{C.RESET}"


def health_color(current: int, maximum: int) -> str:
    """Pick a colour based on how full a bar is."""
    ratio = current / maximum if maximum > 0 else 0
    if ratio > 0.75:
        return C.BRIGHT_GREEN
    if ratio > 0.50:
        return C.YELLOW
    if ratio > 0.25:
        return C.BRIGHT_RED
    return C.RED


def health_bar(current: int, maximum: int, width: int = 10) -> str:
    """Render a coloured health bar like ``[████░░░░░░] 6/8``."""
    filled = round(width * current / maximum) if maximum > 0 else 0
    empty = width - filled
    color = health_color(current, maximum)
    return f"{color}[{'█' * filled}{'░' * empty}]{C.RESET} {current}/{maximum}"
