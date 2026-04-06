"""Entry point for running the game as ``python -m spacefleet``.

Supports three modes:

    python -m spacefleet                          # interactive menu (default)
    python -m spacefleet --server --port 9876     # start game server
    python -m spacefleet --client HOST --port 9876 --user alice  # connect as client
"""

from __future__ import annotations

import argparse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spacefleet",
        description="Spacefleet Combat — tactical spaceship combat game",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--server",
        action="store_true",
        help="Start the game server",
    )
    group.add_argument(
        "--client",
        metavar="HOST",
        type=str,
        default=None,
        help="Connect to a server at HOST",
    )

    # Shared network options
    parser.add_argument("--port", type=int, default=9876, help="TCP port (default: 9876)")

    # Client-only
    parser.add_argument("--user", type=str, default=None, help="Username (client mode)")

    # Server-only
    parser.add_argument(
        "--mode",
        choices=["pve", "pvp", "mixed"],
        default="pve",
        help="Game mode (default: pve)",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=2,
        help="Expected number of players (default: 2)",
    )
    parser.add_argument(
        "--ships-per-player",
        type=int,
        default=3,
        help="Ships per player (default: 3)",
    )

    return parser


def main() -> None:
    """Dispatch to menu, server, or client based on CLI flags."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.server:
        from spacefleet.net.server import main as server_main

        # Build argv for server's own argparse
        server_argv = [
            "--port",
            str(args.port),
            "--mode",
            args.mode,
            "--players",
            str(args.players),
            "--ships-per-player",
            str(args.ships_per_player),
        ]
        server_main(server_argv)

    elif args.client is not None:
        if not args.user:
            parser.error("--user is required in client mode")
        from spacefleet.net.client import main as client_main

        client_argv = [args.client, "--port", str(args.port), "--user", args.user]
        client_main(client_argv)

    else:
        # Default: interactive menu
        from spacefleet.cli.app import main as app_main

        app_main()


if __name__ == "__main__":
    main()
