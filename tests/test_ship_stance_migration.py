"""Ship.stance_state is the source of truth; legacy attrs forward to it."""

from __future__ import annotations

from spacefleet.core.types import Stance, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.models.stance import StanceState


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_ship_has_stance_state_field() -> None:
    ship = _ship()
    assert isinstance(ship.stance_state, StanceState)
    assert ship.stance_state.stance == Stance.STANDARD
    assert ship.stance_state.cooldown_remaining == 0


def test_legacy_stance_reads_from_state() -> None:
    ship = _ship()
    ship.stance_state.stance = Stance.LOCK_ON
    ship.stance_state.cooldown_remaining = 2
    assert ship.stance == Stance.LOCK_ON
    assert ship.stance_cooldown_remaining == 2


def test_legacy_stance_writes_through_to_state() -> None:
    ship = _ship()
    ship.stance = Stance.RELOAD
    ship.stance_cooldown_remaining = 1
    assert ship.stance_state.stance == Stance.RELOAD
    assert ship.stance_state.cooldown_remaining == 1


def test_tick_stance_cooldown_uses_state() -> None:
    ship = _ship()
    ship.stance_state.cooldown_remaining = 2
    ship.tick_stance_cooldown()
    assert ship.stance_state.cooldown_remaining == 1


def test_independent_ships_do_not_share_state() -> None:
    a = _ship()
    b = _ship()
    a.stance = Stance.LOCK_ON
    a.stance_cooldown_remaining = 2
    assert b.stance == Stance.STANDARD
    assert b.stance_cooldown_remaining == 0
