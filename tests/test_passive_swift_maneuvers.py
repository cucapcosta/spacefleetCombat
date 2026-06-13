"""swift_maneuvers adds +5 to fleet speed cap."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.commander.passive_skills import (
    PassiveBus,
    effective_speed_max_with_passives,
)
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def test_swift_maneuvers_adds_5_to_speed_max() -> None:
    state = CoreGameState()
    s = Ship.from_profile(
        "s1",
        "S",
        HULK_HULL,
        make_hulk_weapons(),
        position=None,
        heading=0.0,
    )
    state.add_ship(s)
    cmdr = Commander(
        id="c1",
        name="A",
        faction=Faction.IMPERIAL_NAVY,
        passive_skill_ids=["swift_maneuvers"],
    )
    state.fleets["f1"] = Fleet(
        id="f1",
        commander=cmdr,
        ship_ids=["s1"],
        flagship_ship_id="s1",
    )
    state.passives = PassiveBus.build(state)

    base = s.effective_speed_max
    with_bonus = effective_speed_max_with_passives(s, state)
    assert with_bonus - base == 5.0
