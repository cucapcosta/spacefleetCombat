"""mark_of_chaos buff blocks morale loss on buffed flagship."""

from __future__ import annotations

from spacefleet.commander.commander import ActiveBuff, Commander
from spacefleet.commander.passive_skills import PassiveBus
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def test_mark_of_chaos_blocks_morale_loss_on_flagship() -> None:
    state = CoreGameState()
    ship = Ship.from_profile(
        "flag",
        "Flag",
        HULK_HULL,
        make_hulk_weapons(),
        position=None,
        heading=0.0,
    )
    state.add_ship(ship)
    cmdr = Commander(id="c1", name="Adm", faction=Faction.CHAOS_FLEET)
    cmdr.active_buffs.append(
        ActiveBuff(
            id="mark_of_chaos",
            source_ability_id="mark_of_chaos",
            turns_remaining=3,
            data={"morale_immunity": True},
        )
    )
    state.fleets["f1"] = Fleet(
        id="f1",
        commander=cmdr,
        ship_ids=["flag"],
        flagship_ship_id="flag",
    )
    state.passives = PassiveBus.build(state)

    before = ship.morale
    ship.apply_morale_change(-20, state=state)
    assert ship.morale == before  # no loss
