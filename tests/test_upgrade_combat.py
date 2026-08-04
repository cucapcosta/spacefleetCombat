"""Upgrade combat wiring — AP ammo, lance crits, belt armour."""

from __future__ import annotations

import dataclasses

from spacefleet.combat.damage import apply_damage_pipeline
from spacefleet.combat.projectile_resolution import resolve_projectile_impact
from spacefleet.commander.upgrade_effects import build_ship_with_upgrades
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, SALVAGE_GUN, make_hulk_weapons
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.dice import DiceRoller
from spacefleet.models.projectile import Projectile
from spacefleet.models.ship import Ship
from spacefleet.net.game_state import GameState


class _FixedDice(DiceRoller):
    """d6 always returns *value*; chance() always True."""

    def __init__(self, value: int) -> None:
        super().__init__(seed=1)
        self._value = value

    def d6(self) -> int:
        return self._value

    def chance(self, probability: float) -> bool:
        return probability > 0


def test_armor_delta_lowers_effective_armor() -> None:
    armor5_hull = dataclasses.replace(
        HULK_HULL, armor_prow=5, armor_port=5, armor_starboard=5, armor_stern=5, shields=0
    )
    target = Ship.from_profile("t", "Target", armor5_hull, make_hulk_weapons())
    # Roll of 4 vs armor 5: saved without delta...
    report = apply_damage_pipeline(
        target=target,
        hits=1,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=_FixedDice(4),
    )
    assert report.penetrating == 0
    # ...but penetrates with armor_delta=-1 (AP ammo at close range).
    report = apply_damage_pipeline(
        target=target,
        hits=1,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=_FixedDice(4),
        armor_delta=-1,
    )
    assert report.penetrating == 1


def _projectile_from(attacker: Ship, distance_traveled: float) -> Projectile:
    proj = Projectile(
        id="pr1",
        position=Vector2D(0, 0),
        bearing=0.0,
        speed=SALVAGE_GUN.speed,
        weapon_mount=attacker.weapons[0],
        attacker_id=attacker.id,
        attacker_name=attacker.name,
        attacker_faction=attacker.faction,
        origin=Vector2D(0, 0),
        max_range=SALVAGE_GUN.range,
    )
    proj.distance_traveled = distance_traveled
    return proj


def test_ap_ammo_applies_only_at_close_range() -> None:
    UpgradeRegistry.reset()
    armor5_hull = dataclasses.replace(
        HULK_HULL, armor_prow=5, armor_port=5, armor_starboard=5, armor_stern=5, shields=0
    )
    state = GameState()
    attacker = build_ship_with_upgrades(
        "ap", "AP Ship", HULK_HULL, make_hulk_weapons(), upgrade_ids=["armour_piercing_ammo"]
    )
    target = Ship.from_profile("t2", "Target", armor5_hull, make_hulk_weapons())
    state.add_ship(attacker)
    state.add_ship(target)

    close = resolve_projectile_impact(
        _projectile_from(attacker, SALVAGE_GUN.range * 0.25),
        target,
        dice_roller=_FixedDice(4),
        state=state,
    )
    assert close.penetrating_hits > 0  # armor 5 → 4 with AP; roll 4 penetrates

    target.hull_current = target.hull_max  # reset
    far = resolve_projectile_impact(
        _projectile_from(attacker, SALVAGE_GUN.range * 0.9),
        target,
        dice_roller=_FixedDice(4),
        state=state,
    )
    assert far.penetrating_hits == 0  # no AP at long range; roll 4 vs armor 5 saved
