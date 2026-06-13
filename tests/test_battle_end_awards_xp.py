"""Battle end awards commander XP and bumps surviving crew veterancy."""

from __future__ import annotations

from spacefleet.commander.progression import CrewTierUpEvent, XpGainedEvent
from spacefleet.core.types import Faction
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import resolve_turn


def _winner_takes_all() -> GameState:
    """Imperial fleet wins: every non-Imperial ship (incl. hulks) is destroyed."""
    state = GameState.create_mixed(["imp"], ["cha"], ships_per_player=1, seed=1)
    for ship in state.ships.values():
        if ship.faction != Faction.IMPERIAL_NAVY:
            ship.take_hull_damage(ship.hull.hull_hits)
    state.kills["imp"] = 1  # imperial fleet scored a kill
    return state


def test_battle_end_awards_xp_to_winner() -> None:
    state = _winner_takes_all()
    assert state.is_game_over()
    cmdr = state.fleets["imp"].commander
    assert cmdr is not None
    xp_before = cmdr.xp

    log = resolve_turn(state, {})

    assert any(isinstance(e, XpGainedEvent) for e in log.events)
    assert cmdr.xp > xp_before


def test_battle_end_bumps_crew_veterancy() -> None:
    state = _winner_takes_all()
    imp_id = state.player_ships["imp"][0]
    before = state.ships[imp_id].battles_survived

    resolve_turn(state, {})

    assert state.ships[imp_id].battles_survived == before + 1


def test_xp_awarded_only_once() -> None:
    state = _winner_takes_all()
    cmdr = state.fleets["imp"].commander
    assert cmdr is not None

    resolve_turn(state, {})
    xp_after_first = cmdr.xp
    log2 = resolve_turn(state, {})

    assert cmdr.xp == xp_after_first  # no double award
    assert not any(isinstance(e, (XpGainedEvent, CrewTierUpEvent)) for e in log2.events)
