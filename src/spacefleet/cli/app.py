"""Main application — menus and entry point."""

from __future__ import annotations

from spacefleet.cli.colors import C, bold, colored, dim
from spacefleet.cli.terminal_ui import MenuOption, TerminalClosed, TerminalUI

# ─────────────────────────────────────────────────────────────────
# Banner & menu text
# ─────────────────────────────────────────────────────────────────

_INNER = 50  # box width between the two borders
_TOP = colored("╔" + "═" * _INNER + "╗", C.BRIGHT_CYAN)
_BOT = colored("╚" + "═" * _INNER + "╝", C.BRIGHT_CYAN)
_BAR = colored("║", C.BRIGHT_CYAN)
_TITLE = "S P A C E F L E E T   C O M B A T"
_VER = "Campaign Edition v0.2"


def _row(styled: str, plain: str) -> str:
    return f"{_BAR}  {styled}{' ' * (_INNER - 2 - len(plain))}{_BAR}"


BANNER = f"""
{_TOP}
{_row(bold(_TITLE), _TITLE)}
{_row(dim(_VER), _VER)}
{_BOT}
"""

MENU = f"""
  {colored("[1]", C.BRIGHT_YELLOW)} Campaign
  {colored("[2]", C.BRIGHT_YELLOW)} Connect to Server
  {colored("[3]", C.BRIGHT_YELLOW)} Fleet Builder
  {colored("[4]", C.RED)} Quit
"""


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


def main(*, ui: TerminalUI | None = None) -> None:
    """Application entry point with one shared terminal UI instance."""
    ui = ui or TerminalUI()
    try:
        with ui.session():
            while True:
                choice = ui.choose(
                    "SPACEFLEET COMBAT",
                    [
                        MenuOption("campaign", "Campaign"),
                        MenuOption("connect", "Connect to Server"),
                        MenuOption("fleet", "Fleet Builder"),
                        MenuOption("quit", "Quit"),
                    ],
                    context=BANNER,
                )
                if choice is None or choice == "quit":
                    break
                if choice == "campaign":
                    from spacefleet.cli.campaign_cmd import run_campaign_menu

                    run_campaign_menu(ui=ui)
                elif choice == "connect":
                    with ui.suspended():
                        _connect_to_server()
                elif choice == "fleet":
                    from spacefleet.cli.fleet_builder_cmd import run_fleet_builder

                    run_fleet_builder(ui=ui)
    except TerminalClosed:
        pass
    ui.show(f"\n  {dim('Ave Imperator. The Emperor protects.')}\n")
