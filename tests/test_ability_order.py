"""AbilityOrder construction + field semantics."""

from __future__ import annotations

from spacefleet.core.types import Vector2D
from spacefleet.net.commands import AbilityOrder


def test_ability_order_defaults() -> None:
    o = AbilityOrder(fleet_id="p1", ability_id="call_to_arms")
    assert o.target_ship_id is None
    assert o.target_position is None


def test_ability_order_with_target_ship() -> None:
    o = AbilityOrder(
        fleet_id="p1",
        ability_id="concentrated_fire",
        target_ship_id="enemy_1",
    )
    assert o.target_ship_id == "enemy_1"


def test_ability_order_with_position() -> None:
    o = AbilityOrder(
        fleet_id="p1",
        ability_id="warp_rift",
        target_position=Vector2D(10.0, 20.0),
    )
    assert o.target_position == Vector2D(10.0, 20.0)
