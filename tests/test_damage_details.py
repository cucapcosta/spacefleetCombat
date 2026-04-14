"""DamageReport now carries per-hit HitDetail records."""

from __future__ import annotations

from spacefleet.combat.damage import DamageReport, HitDetail, apply_damage_pipeline
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


def test_report_has_details_list() -> None:
    report = DamageReport()
    assert report.details == []


def test_pipeline_records_shield_blocks_as_details() -> None:
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
    assert len(report.details) == 2
    assert all(d.blocked_by_shield for d in report.details)


def test_pipeline_records_armor_rolls() -> None:
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
    armor_details = [d for d in report.details if not d.blocked_by_shield]
    assert len(armor_details) == 3
    for d in armor_details:
        assert d.armor_value > 0
        assert 1 <= d.armor_roll <= 6
        assert d.penetrated == (d.armor_roll >= d.armor_value)


def test_pipeline_does_not_apply_hull_damage() -> None:
    """Callers own the hull.take_hull_damage step (after Brace post-processing)."""
    ship = _ship()
    ship.shields_current = 0
    original_hull = ship.hull_current
    dr = DiceRoller(seed=1)
    apply_damage_pipeline(
        target=ship,
        hits=3,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=dr,
    )
    assert ship.hull_current == original_hull


def test_resolution_imports_hit_detail_from_damage() -> None:
    """resolution.py should re-import HitDetail from combat.damage."""
    from spacefleet.combat import resolution

    assert resolution.HitDetail is HitDetail
