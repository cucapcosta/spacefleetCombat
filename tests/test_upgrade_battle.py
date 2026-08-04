"""Upgrade effects exercised through resolve_turn."""

from __future__ import annotations

from spacefleet.commander.upgrade_effects import (
    FireSuppressedByUpgradeEvent,
    build_ship_with_upgrades,
)
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import resolve_turn


class _AlwaysChanceDice(DiceRoller):
    def __init__(self) -> None:
        super().__init__(seed=1)

    def chance(self, probability: float) -> bool:
        return probability > 0

    def d6(self) -> int:
        return 6  # leadership fire check always fails → isolates the upgrade


def test_fire_suppression_extinguishes_in_end_phase() -> None:
    UpgradeRegistry.reset()
    state = GameState()
    state.dice = _AlwaysChanceDice()
    ship = build_ship_with_upgrades(
        "fs",
        "Fireproof",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["fire_suppression_system"],
        position=Vector2D(0, 0),
    )
    ship.fires = 2
    state.add_ship(ship)

    log = resolve_turn(state, {"fs": Command(ship_id="fs", action="pass", args={})})

    assert ship.fires == 1  # one fire suppressed by the upgrade
    assert any(isinstance(e, FireSuppressedByUpgradeEvent) for e in log.events)


def test_combustion_regen_bonus_applies() -> None:
    UpgradeRegistry.reset()
    state = GameState()
    ship = build_ship_with_upgrades(
        "ct",
        "Tanker",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["extended_combustion_tanks"],
        position=Vector2D(0, 0),
    )
    ship.combustion = 50
    state.add_ship(ship)

    resolve_turn(state, {"ct": Command(ship_id="ct", action="pass", args={})})

    assert ship.combustion == 50 + 15 + 5  # base 15 + upgrade bonus 5


def test_plain_ship_combustion_unchanged() -> None:
    state = GameState()
    ship = Ship.from_profile("pl", "Plain", HULK_HULL, make_hulk_weapons(), position=Vector2D(0, 0))
    ship.combustion = 50
    state.add_ship(ship)
    resolve_turn(state, {"pl": Command(ship_id="pl", action="pass", args={})})
    assert ship.combustion == 65


def test_upgraded_ship_full_turn_integration() -> None:
    """Turbo weaponry + shield capacitor + master of signals through resolve_turn."""
    UpgradeRegistry.reset()
    import dataclasses as dc

    from spacefleet.commander.passive_skills import (
        battery_firepower_bonus,
        end_of_turn_shield_regen,
    )
    from spacefleet.core.types import Stance

    state = GameState()
    shielded_hull = dc.replace(HULK_HULL, shields=4)
    ship = build_ship_with_upgrades(
        "int1",
        "Integrated",
        shielded_hull,
        make_hulk_weapons(),
        upgrade_ids=["turbo_weaponry", "auxiliary_shield_capacitor", "master_of_signals"],
        position=Vector2D(0, 0),
    )
    ship.shields_current = 1
    state.add_ship(ship)

    log = resolve_turn(state, {"int1": Command(ship_id="int1", action="pass", args={})})
    assert log is not None

    # Capacitor: base regen 1 + upgrade 1 = 2 → shields 1 → 3
    assert ship.shields_current == 3
    # Bus carries the turbo bonus after the turn's build
    assert battery_firepower_bonus(state, ship, ship, ship.weapons[0]) == 1
    assert end_of_turn_shield_regen(state, ship) == 1
    # Master of signals: cooldown 1 lower than the stance's configured cooldown
    from spacefleet.data.stance_registry import StanceRegistry

    ship.switch_stance(Stance.LOCK_ON)
    expected = max(0, StanceRegistry.get_for(Stance.LOCK_ON).switch_cooldown - 1)
    assert ship.stance_cooldown_remaining == expected
