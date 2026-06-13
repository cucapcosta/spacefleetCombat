"""veteran_crews reduces morale loss by 25%."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def test_morale_loss_reduced_by_veteran_crews() -> None:
    state = CoreGameState()
    ship = Ship.from_profile(
        "s1",
        "Ship",
        HULK_HULL,
        make_hulk_weapons(),
        position=None,
        heading=0.0,
    )
    state.add_ship(ship)
    cmdr = Commander(
        id="c1",
        name="Adm",
        faction=Faction.CHAOS_FLEET,
        passive_skill_ids=["veteran_crews"],
    )
    state.fleets["f1"] = Fleet(
        id="f1",
        commander=cmdr,
        ship_ids=["s1"],
        flagship_ship_id="s1",
    )

    from spacefleet.commander.passive_skills import PassiveBus

    state.passives = PassiveBus.build(state)  # registrations pull veteran_crews in

    before = ship.morale
    ship.apply_morale_change(-20, state=state)
    # 20 * 0.75 = 15 loss
    assert before - ship.morale == 15


def test_morale_loss_raw_when_no_state() -> None:
    ship = Ship.from_profile(
        "s1",
        "Ship",
        HULK_HULL,
        make_hulk_weapons(),
        position=None,
        heading=0.0,
    )
    before = ship.morale
    ship.apply_morale_change(-20)  # no state kwarg
    assert before - ship.morale == 20
