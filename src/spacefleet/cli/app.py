"""Main application — menus, demo setup, and entry point."""

from __future__ import annotations

from spacefleet.cli.colors import C, bold, colored, dim
from spacefleet.cli.display import format_kit_option
from spacefleet.cli.game_cmd import DemoBattle
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import (
    DAUNTLESS_HULL,
    HULK_HULL,
    make_broadside_kit,
    make_hulk_weapons,
    make_lance_kit,
    spawn_target,
)
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship

# ─────────────────────────────────────────────────────────────────
# Banner & menu text
# ─────────────────────────────────────────────────────────────────

_TOP = colored("╔══════════════════════════════════════════════════╗", C.BRIGHT_CYAN)
_BOT = colored("╚══════════════════════════════════════════════════╝", C.BRIGHT_CYAN)
_BAR = colored("║", C.BRIGHT_CYAN)
_TITLE = bold("S P A C E F L E E T   C O M B A T")
_VER = dim("Tech Demo v0.1")

BANNER = f"""
{_TOP}
{_BAR}  {_TITLE}           {_BAR}
{_BAR}  {_VER}                                {_BAR}
{_BOT}
"""

MENU = f"""
  {colored("[1]", C.BRIGHT_YELLOW)} Start Demo
  {colored("[2]", C.BRIGHT_YELLOW)} Connect to Server
  {colored("[3]", C.DIM)} Configuration {dim("(not yet available)")}
  {colored("[4]", C.RED)} Quit
"""


# ─────────────────────────────────────────────────────────────────
# Kit selection
# ─────────────────────────────────────────────────────────────────


def _select_weapon_kit() -> int:
    """Let the player choose a weapon loadout.

    Returns 1 for Broadside, 2 for Lance, 0 for cancel.
    """
    print(f"\n  {bold('Select your weapon loadout for the Dauntless Light Cruiser:')}\n")

    print(
        format_kit_option(
            "[A] Broadside Brawler",
            "Heavy broadsides for flanking engagements. Present your sides to "
            "unleash maximum firepower.",
            [
                ("Port Battery", "Macro-Cannon Mk.III", "str 6, range 45 GU"),
                ("Starboard Battery", "Macro-Cannon Mk.III", "str 6, range 45 GU"),
                ("Prow Weapon Bay", "Macro-Cannon Mk.II", "str 4, range 45 GU"),
            ],
        )
    )
    print()
    print(
        format_kit_option(
            "[B] Prow Lancer",
            "Balanced broadsides with a prow lance that bypasses armor entirely. "
            "Point your nose at the enemy.",
            [
                ("Port Battery", "Macro-Cannon Mk.II", "str 4, range 45 GU"),
                ("Starboard Battery", "Macro-Cannon Mk.II", "str 4, range 45 GU"),
                ("Prow Weapon Bay", "Lance Mk.II", "str 2, range 60 GU, ignores armor"),
            ],
        )
    )

    while True:
        try:
            choice = (
                input(
                    f"\n  Choose loadout"
                    f" ({colored('A', C.BRIGHT_YELLOW)}/{colored('B', C.BRIGHT_YELLOW)}): "
                )
                .strip()
                .upper()
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice in ("A", "1"):
            return 1
        if choice in ("B", "2"):
            return 2
        print("  Please enter A or B.")


# ─────────────────────────────────────────────────────────────────
# Demo setup
# ─────────────────────────────────────────────────────────────────


def _start_demo() -> None:
    """Set up and run the tech demo battle."""
    kit_choice = _select_weapon_kit()
    if kit_choice == 0:
        return

    # Build weapon loadout
    if kit_choice == 1:
        weapons = make_broadside_kit()
        kit_name = "Broadside Brawler"
    else:
        weapons = make_lance_kit()
        kit_name = "Prow Lancer"

    print(f"\n  Loadout selected: {colored(kit_name, C.BRIGHT_YELLOW)}")

    # Create player ship — starts stationary at the origin, heading north
    player = Ship.from_profile(
        ship_id="player",
        name="ISS Dauntless",
        hull=DAUNTLESS_HULL,
        weapons=weapons,
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )

    # Create first target hulk — 30 GU dead ahead
    first_target = Ship.from_profile(
        ship_id="hulk_1",
        name="Derelict Hulk #1",
        hull=HULK_HULL,
        weapons=make_hulk_weapons(),
        position=Vector2D(0.0, 30.0),
        heading=180.0,
    )

    # Create dice roller (un-seeded for real randomness)
    dice = DiceRoller()

    # Run!
    battle = DemoBattle(
        player=player,
        targets=[first_target],
        dice_roller=dice,
        spawn_fn=spawn_target,
    )
    battle.run()


# ─────────────────────────────────────────────────────────────────
# Connect to server
# ─────────────────────────────────────────────────────────────────


def _connect_to_server() -> None:
    """Prompt for server address and username, then launch the client."""
    import asyncio

    from spacefleet.cli.prompts import prompt_client_setup
    from spacefleet.net.client import SpacefleetClient

    config = prompt_client_setup()
    if config is None:
        return

    host, port, username = config["host"], config["port"], config["username"]
    print(
        f"\n  Connecting to {colored(host, C.BRIGHT_CYAN)}"
        f":{colored(str(port), C.BRIGHT_CYAN)}"
        f" as {colored(username, C.BRIGHT_YELLOW)}...\n"
    )

    client = SpacefleetClient(host=host, port=port, username=username)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print(f"\n  {dim('Disconnected.')}")


# ─────────────────────────────────────────────────────────────────
# Main menu
# ─────────────────────────────────────────────────────────────────


def main() -> None:
    """Application entry point — main menu loop."""
    while True:
        print(BANNER)
        print(MENU)

        try:
            choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "1":
            _start_demo()
        elif choice == "2":
            _connect_to_server()
        elif choice == "3":
            print(f"\n  {dim('No configuration options available yet.')}\n")
        elif choice in ("4", "quit", "q"):
            break
        else:
            print(f"  {dim('Please enter 1, 2, 3, or 4.')}")

    print(f"\n  {dim('Ave Imperator. The Emperor protects.')}\n")
