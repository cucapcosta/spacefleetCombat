"""Reusable interactive prompt helpers for server & client setup.

All prompts follow the visual style established in ``cli/app.py``:
two-space indent, dim defaults in brackets, red errors, bold headers.
Every function returns ``None`` on Ctrl-C / Ctrl-D so callers can
cleanly abort.
"""

from __future__ import annotations

from typing import Any  # noqa: TCH003 — used in return annotations at runtime

from spacefleet.cli.colors import C, bold, colored, dim

# ── Low-level helpers ─────────────────────────────────────────


def prompt_with_default(label: str, default: str) -> str | None:
    """Prompt with a dim default shown in brackets.

    Returns the user's input (stripped) or *default* if empty.
    Returns ``None`` on EOF / KeyboardInterrupt.
    """
    try:
        value = input(f"  {label} [{colored(default, C.DIM)}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return value or default


def prompt_required(label: str) -> str | None:
    """Prompt that re-asks until a non-empty value is provided.

    Returns ``None`` on EOF / KeyboardInterrupt.
    """
    while True:
        try:
            value = input(f"  {label}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if value:
            return value
        print(f"  {colored(f'{label} is required.', C.RED)}")


def prompt_int(
    label: str,
    default: int,
    *,
    min_val: int = 1,
    max_val: int = 65535,
) -> int | None:
    """Prompt for an integer with range validation.

    Shows *default* in dim brackets.  Re-prompts on invalid input.
    Returns ``None`` on EOF / KeyboardInterrupt.
    """
    while True:
        raw = prompt_with_default(label, str(default))
        if raw is None:
            return None
        try:
            value = int(raw)
        except ValueError:
            print(f"  {colored('Please enter a valid number.', C.RED)}")
            continue
        if value < min_val or value > max_val:
            print(f"  {colored(f'Must be between {min_val} and {max_val}.', C.RED)}")
            continue
        return value


def prompt_choice(
    label: str,
    options: list[tuple[str, str]],
    default: int = 1,
) -> str | None:
    """Display a numbered menu and return the chosen value string.

    *options* is a list of ``(value, description)`` tuples, e.g.
    ``[("pve", "PvE — Players vs AI")]``.

    *default* is the 1-based index of the pre-selected option.
    Returns ``None`` on EOF / KeyboardInterrupt.
    """
    print(f"  {label}:")
    for i, (_value, desc) in enumerate(options, 1):
        marker = f" {dim('(default)')}" if i == default else ""
        print(f"    {colored(f'[{i}]', C.BRIGHT_YELLOW)} {desc}{marker}")

    while True:
        raw = prompt_with_default("Select", str(default))
        if raw is None:
            return None
        try:
            idx = int(raw)
        except ValueError:
            print(f"  {colored(f'Please enter a number from 1 to {len(options)}.', C.RED)}")
            continue
        if 1 <= idx <= len(options):
            return options[idx - 1][0]
        print(f"  {colored(f'Please enter a number from 1 to {len(options)}.', C.RED)}")


# ── High-level orchestrators ──────────────────────────────────


_SERVER_BANNER = (
    f"\n{colored('╔══════════════════════════════════════════════════╗', C.BRIGHT_CYAN)}\n"
    f"{colored('║', C.BRIGHT_CYAN)}  {bold('S E R V E R   S E T U P')}                        "
    f"{colored('║', C.BRIGHT_CYAN)}\n"
    f"{colored('╚══════════════════════════════════════════════════╝', C.BRIGHT_CYAN)}\n"
)

_CLIENT_BANNER = (
    f"\n{colored('╔══════════════════════════════════════════════════╗', C.BRIGHT_CYAN)}\n"
    f"{colored('║', C.BRIGHT_CYAN)}  {bold('C O N N E C T   T O   S E R V E R')}              "
    f"{colored('║', C.BRIGHT_CYAN)}\n"
    f"{colored('╚══════════════════════════════════════════════════╝', C.BRIGHT_CYAN)}\n"
)


def prompt_server_setup() -> dict[str, Any] | None:
    """Interactive server configuration.

    Returns a dict matching ``SpacefleetServer.__init__`` kwargs,
    or ``None`` if the user cancels.
    """
    print(_SERVER_BANNER)

    port = prompt_int("Port", 9876, min_val=1, max_val=65535)
    if port is None:
        return None

    print()
    mode = prompt_choice(
        "Game mode",
        [
            ("pve", "PvE  — Players vs AI enemies"),
            ("pvp", "PvP  — Players vs players"),
            ("mixed", "Mixed — Players + AI vs players + AI"),
        ],
    )
    if mode is None:
        return None

    print()
    expected_players = prompt_int("Number of players", 2, min_val=1, max_val=8)
    if expected_players is None:
        return None

    ships_per_player = prompt_int("Ships per player", 3, min_val=1, max_val=10)
    if ships_per_player is None:
        return None

    print()
    return {
        "host": "0.0.0.0",
        "port": port,
        "mode": mode,
        "expected_players": expected_players,
        "ships_per_player": ships_per_player,
    }


def prompt_client_setup() -> dict[str, Any] | None:
    """Interactive client connection setup.

    Returns ``{"host": str, "port": int, "username": str}``
    or ``None`` if the user cancels.
    """
    print(_CLIENT_BANNER)

    host = prompt_with_default("Server address", "localhost")
    if host is None:
        return None

    port = prompt_int("Port", 9876, min_val=1, max_val=65535)
    if port is None:
        return None

    username = prompt_required("Username")
    if username is None:
        return None

    print()
    return {"host": host, "port": port, "username": username}
