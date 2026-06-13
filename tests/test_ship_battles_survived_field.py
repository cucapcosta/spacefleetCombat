"""Ship exposes battles_survived (persisted across battles)."""

from __future__ import annotations

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        "s1",
        "Test",
        HULK_HULL,
        make_hulk_weapons(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_battles_survived_defaults_zero() -> None:
    assert _ship().battles_survived == 0


def test_battles_survived_is_mutable() -> None:
    s = _ship()
    s.battles_survived = 5
    assert s.battles_survived == 5
