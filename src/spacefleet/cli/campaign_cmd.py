"""Initial playable entry point for a new local campaign."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.campaign.battle import build_battle
from spacefleet.campaign.rules import INITIAL_CREDITS, new_campaign
from spacefleet.cli.fleet_builder_cmd import run_fleet_builder
from spacefleet.cli.local_battle import LocalBattleController
from spacefleet.cli.prompts import prompt_choice, prompt_required
from spacefleet.core.types import Faction

if TYPE_CHECKING:
    from pathlib import Path


def _prompt_optional_seed() -> int | None:
    while True:
        try:
            raw = input("  Campaign seed (blank for random): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if not raw:
            return None
        try:
            seed = int(raw)
        except ValueError:
            print("  Seed must be a non-negative integer.")
            continue
        if seed < 0:
            print("  Seed must be a non-negative integer.")
            continue
        return seed


def run_new_campaign(save_path: Path | None = None) -> None:
    """Create a fleet and play encounter one without persistence or economy."""
    del save_path  # Reserved for the interval/save flow added in Task 8.
    faction_value = prompt_choice(
        "Faction",
        [
            (Faction.IMPERIAL_NAVY.value, "Imperial Navy"),
            (Faction.CHAOS_FLEET.value, "Chaos Fleet"),
        ],
    )
    if faction_value is None:
        return
    name = prompt_required("Fleet and commander name")
    if name is None:
        return
    try:
        seed = _prompt_optional_seed()
    except (EOFError, KeyboardInterrupt):
        return

    faction = Faction(faction_value)
    fleet = run_fleet_builder(
        faction=faction,
        budget=INITIAL_CREDITS,
        name=name,
    )
    if fleet is None:
        return
    try:
        campaign = new_campaign(fleet, name, seed)
        outcome = LocalBattleController(build_battle(campaign)).run()
    except ValueError as exc:
        print(f"  Campaign cannot start: {exc}")
        return
    print(f"  Battle ended: {outcome.value.replace('_', ' ')}.")
