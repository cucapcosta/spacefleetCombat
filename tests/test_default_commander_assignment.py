"""Scenario setup auto-assigns a starter commander to each player fleet."""

from __future__ import annotations

from spacefleet.core.types import Faction
from spacefleet.net.game_state import GameState


def test_pve_scenario_populates_fleets_with_commanders() -> None:
    state = GameState.create_pve(["p1"], ships_per_player=3, seed=1)
    assert "p1" in state.fleets
    fleet = state.fleets["p1"]
    assert fleet.commander is not None
    assert fleet.commander.level == 1
    assert fleet.flagship_ship_id is not None
    flagship = state.ships[fleet.flagship_ship_id]
    # Heaviest hull: Dauntless (light_cruiser) beats Sword (escort).
    assert flagship.hull.classification.value == "light_cruiser"
    assert "concentrated_fire" in fleet.commander.active_ability_ids
    assert fleet.commander.faction == Faction.IMPERIAL_NAVY
    # Charges initialised for each active ability.
    assert fleet.commander.ability_state["concentrated_fire"].remaining_charges > 0


def test_ai_hulks_get_no_commander() -> None:
    state = GameState.create_pve(["p1"], ships_per_player=2, seed=1)
    ai_fleets = [f for fid, f in state.fleets.items() if fid.startswith("ai_")]
    assert ai_fleets  # hulks produced fleets
    for fleet in ai_fleets:
        assert fleet.commander is None


def test_chaos_fleet_gets_chaos_commander() -> None:
    state = GameState.create_mixed(["imp"], ["cha"], ships_per_player=2, seed=2)
    cha = state.fleets["cha"]
    assert cha.commander is not None
    assert cha.commander.faction == Faction.CHAOS_FLEET
    assert "mark_of_chaos" in cha.commander.active_ability_ids
