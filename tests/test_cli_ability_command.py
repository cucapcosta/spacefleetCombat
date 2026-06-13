"""CLI ability-command parsing + commander status line (Task 29)."""

from __future__ import annotations

from spacefleet.cli.game_cmd import format_commander_status, parse_ability_command
from spacefleet.commander.commander import AbilityState, Commander
from spacefleet.core.types import Faction, Vector2D


def test_parse_bare_ability() -> None:
    order = parse_ability_command(["emergency_repairs"], "f1")
    assert order is not None
    assert order.fleet_id == "f1"
    assert order.ability_id == "emergency_repairs"
    assert order.target_ship_id is None
    assert order.target_position is None


def test_parse_ability_with_target_ship() -> None:
    order = parse_ability_command(["concentrated_fire", "enemy3"], "f1")
    assert order is not None
    assert order.target_ship_id == "enemy3"


def test_parse_ability_with_position() -> None:
    order = parse_ability_command(["micro_warp_jump", "at", "12.5", "-4"], "f1")
    assert order is not None
    assert order.target_position == Vector2D(12.5, -4.0)


def test_parse_rejects_empty() -> None:
    assert parse_ability_command([], "f1") is None


def test_parse_rejects_bad_position() -> None:
    assert parse_ability_command(["warp", "at", "x", "y"], "f1") is None
    assert parse_ability_command(["warp", "at", "1"], "f1") is None


def test_parse_rejects_extra_tokens() -> None:
    assert parse_ability_command(["a", "b", "c"], "f1") is None


def test_commander_status_line() -> None:
    cmdr = Commander(
        id="c",
        name="Adm",
        faction=Faction.IMPERIAL_NAVY,
        level=3,
        xp=450,
        active_ability_ids=["concentrated_fire", "emergency_repairs"],
    )
    cmdr.ability_state["concentrated_fire"] = AbilityState(
        remaining_charges=1, cooldown_remaining=2
    )
    cmdr.ability_state["emergency_repairs"] = AbilityState(remaining_charges=2)
    line = format_commander_status(cmdr)
    assert "Lvl 3" in line
    assert "XP 450" in line
    assert "concentrated_fire (1c, cd 2)" in line
    assert "emergency_repairs (2c)" in line
