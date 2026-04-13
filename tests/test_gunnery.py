"""Tests for combat.gunnery — gunnery table lookup + battery resolver."""
from __future__ import annotations

from spacefleet.combat.gunnery import (
    GUNNERY_COLUMNS,
    GUNNERY_TABLE,
    column_index,
    lookup_hits,
    target_aspect,
)
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship(*, x: float, y: float, heading: float) -> Ship:
    return Ship.from_profile(
        ship_id=f"s_{x}_{y}",
        name="S",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(x, y),
        heading=heading,
    )


def test_table_has_16_rows():
    assert len(GUNNERY_TABLE) == 16
    assert GUNNERY_COLUMNS == [
        "far_closing", "closing", "abeam", "running", "far_running",
    ]


def test_lookup_clamps_strength():
    assert lookup_hits(strength=1, column=2) == 1  # 1@abeam = 1
    assert lookup_hits(strength=99, column=4) == 9  # clamped to 16


def test_column_index_centred_at_2():
    assert column_index(aspect_shift=0, stance_shift=0) == 2
    assert column_index(aspect_shift=-1, stance_shift=0) == 1
    assert column_index(aspect_shift=1, stance_shift=1) == 4
    assert column_index(aspect_shift=-1, stance_shift=-1) == 0
    # Clamped at 0 / 4
    assert column_index(aspect_shift=-2, stance_shift=-2) == 0
    assert column_index(aspect_shift=2, stance_shift=2) == 4


def test_target_aspect_closing_when_prow_to_attacker():
    target = _ship(x=0, y=0, heading=180.0)  # facing -y
    attacker = _ship(x=0, y=-30, heading=0.0)  # below, but target faces it
    name, shift = target_aspect(attacker, target)
    assert name == "closing"
    assert shift == -1
