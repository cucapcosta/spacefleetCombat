"""Upgrade effects — Ship fields, hull mods, ship builder."""

from __future__ import annotations

from spacefleet.commander.passive_skills import (
    PassiveBus,
    battery_firepower_bonus,
    end_of_turn_shield_regen,
)
from spacefleet.commander.upgrade_effects import (
    apply_upgrades_to_hull,
    build_ship_with_upgrades,
)
from spacefleet.core.types import Stance, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.models.ship import Ship
from spacefleet.net.game_state import GameState


def _ship(**kwargs: object) -> Ship:
    return Ship.from_profile("s1", "Test Ship", HULK_HULL, make_hulk_weapons(), **kwargs)  # type: ignore[arg-type]


def test_ship_upgrade_fields_default_noop() -> None:
    ship = _ship()
    assert ship.upgrade_ids == []
    assert ship.stance_cooldown_reduction == 0
    assert ship.combustion_regen_bonus == 0
    assert ship.belt_armour_spent is False


def test_from_profile_upgrade_ids_passthrough() -> None:
    ship = _ship(upgrade_ids=["turbo_weaponry"])
    assert ship.upgrade_ids == ["turbo_weaponry"]


def test_stance_cooldown_reduction_applies_on_switch() -> None:
    plain = _ship()
    reduced = _ship()
    reduced.stance_cooldown_reduction = 1
    assert plain.switch_stance(Stance.LOCK_ON) is True
    assert reduced.switch_stance(Stance.LOCK_ON) is True
    assert reduced.stance_cooldown_remaining == max(0, plain.stance_cooldown_remaining - 1)


def test_apply_upgrades_to_hull_stats() -> None:
    UpgradeRegistry.reset()
    modded = apply_upgrades_to_hull(
        HULK_HULL,
        [
            "additional_void_shield",
            "reinforced_prow",
            "extra_turrets",
            "efficient_plasma_thrusters",
            "enhanced_maneuvers",
            "improved_augur_array",
            "crew_quarters",
        ],
    )
    assert modded.shields == HULK_HULL.shields + 1
    assert modded.armor_prow == HULK_HULL.armor_prow + 1
    assert modded.turrets == HULK_HULL.turrets + 2
    assert modded.speed == HULK_HULL.speed + 5
    assert modded.turn_rate == HULK_HULL.turn_rate + 15
    assert modded.sensor_range == HULK_HULL.sensor_range + 20
    assert modded.base_morale == HULK_HULL.base_morale + 15


def test_build_ship_with_upgrades_state_fields() -> None:
    UpgradeRegistry.reset()
    ship = build_ship_with_upgrades(
        "up1",
        "Upgraded",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=[
            "extended_combustion_tanks",
            "veteran_crew",
            "master_of_signals",
        ],
    )
    assert ship.combustion_max == 125
    assert ship.combustion == 125  # starts full
    assert ship.combustion_regen_bonus == 5
    assert ship.stance_cooldown_reduction == 1
    assert ship.crew_tier == 2  # veteran_crew → Experienced
    assert ship.upgrade_ids == [
        "extended_combustion_tanks",
        "veteran_crew",
        "master_of_signals",
    ]


def test_build_ship_with_upgrades_composes_with_doctrine() -> None:
    UpgradeRegistry.reset()
    ship = build_ship_with_upgrades(
        "up2",
        "Upgraded Nurgle",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["additional_void_shield"],
        doctrine_id="mark_of_nurgle",
    )
    # Nurgle: +2 hull, -5 speed; upgrade: +1 shields
    assert ship.hull_max == HULK_HULL.hull_hits + 2
    assert ship.shields_max == HULK_HULL.shields + 1
    assert ship.doctrine_id == "mark_of_nurgle"


def test_build_ship_without_upgrades_is_plain() -> None:
    ship = build_ship_with_upgrades("up3", "Plain", HULK_HULL, make_hulk_weapons(), upgrade_ids=[])
    assert ship.hull_max == HULK_HULL.hull_hits
    assert ship.combustion_max == 100


def test_turbo_weaponry_and_capacitor_register_per_ship() -> None:
    UpgradeRegistry.reset()
    state = GameState()
    upgraded = build_ship_with_upgrades(
        "u1",
        "Upgraded",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["turbo_weaponry", "auxiliary_shield_capacitor"],
        position=Vector2D(0, 0),
    )
    plain = Ship.from_profile("p1", "Plain", HULK_HULL, make_hulk_weapons())
    state.add_ship(upgraded)
    state.add_ship(plain)
    state.passives = PassiveBus.build(state)

    weapon = upgraded.weapons[0]
    assert battery_firepower_bonus(state, upgraded, plain, weapon) == 1
    assert battery_firepower_bonus(state, plain, upgraded, weapon) == 0  # isolation
    assert end_of_turn_shield_regen(state, upgraded) == 1
    assert end_of_turn_shield_regen(state, plain) == 0
