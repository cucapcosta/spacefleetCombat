"""Tests for combat.damage — shield → armor → hull pipeline."""
from __future__ import annotations

from spacefleet.combat.damage import DamageReport, apply_damage_pipeline
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="t",
        name="T",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 30.0),
        heading=180.0,
    )


def test_shields_absorb_first():
    ship = _ship()
    ship.shields_current = 3
    dr = DiceRoller(seed=1)
    report = apply_damage_pipeline(
        target=ship,
        hits=2,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=dr,
    )
    assert report.shield_blocked == 2
    assert ship.shields_current == 1


def test_overflow_rolls_armor():
    ship = _ship()
    ship.shields_current = 0
    dr = DiceRoller(seed=42)
    report = apply_damage_pipeline(
        target=ship,
        hits=3,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=dr,
    )
    assert isinstance(report, DamageReport)
    assert report.shield_blocked == 0
    assert report.penetrating + report.armor_saves == 3


def test_zero_hits_short_circuits():
    ship = _ship()
    dr = DiceRoller(seed=1)
    report = apply_damage_pipeline(
        target=ship,
        hits=0,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=dr,
    )
    assert report.hull_damage == 0
    assert report.penetrating == 0
