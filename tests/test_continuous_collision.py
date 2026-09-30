"""Continuous salvo collision (spec 2026-09-30 "Colisão contínua").

Ships and salvos advance together in straight sub-steps; a hit is the first
instant their relative distance reaches ``HIT_RADIUS``.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from spacefleet.combat.projectile_resolution import HIT_RADIUS
from spacefleet.core.game_loop import advance_half
from spacefleet.core.types import Faction, Vector2D, heading_to_vector
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.dice import DiceRoller
from spacefleet.models.projectile import Projectile
from spacefleet.models.ship import Ship
from spacefleet.net.commands import Command, Maneuver
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import SalvoImpactEvent, SalvoLaunchEvent, resolve_turn
from spacefleet.phases.movement_phase import MoveOrder, apply_move_orders, drift_ship


class _AlwaysHitDice(DiceRoller):
    def roll_d6(self, count: int) -> list[int]:
        return [6] * count


def _ship(
    ship_id: str,
    *,
    x: float,
    y: float,
    heading: float = 0.0,
    speed: float = 0.0,
    turn_rate: float = 60.0,
) -> Ship:
    hull = replace(
        DAUNTLESS_HULL,
        faction=Faction.CHAOS_FLEET,
        speed=40.0,
        turn_rate=turn_rate,
    )
    ship = Ship.from_profile(
        ship_id=ship_id,
        name=ship_id,
        hull=hull,
        weapons=make_broadside_kit(),
        position=Vector2D(x, y),
        heading=heading,
        speed=speed,
    )
    return ship


def _salvo(
    proj_id: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
    bearing: float = 0.0,
    speed: float = 40.0,
    max_range: float = 100.0,
) -> Projectile:
    mount = make_broadside_kit()[0]
    return Projectile(
        id=proj_id,
        position=Vector2D(x, y),
        bearing=bearing,
        speed=speed,
        weapon_mount=mount,
        attacker_id="attacker",
        attacker_name="Attacker",
        attacker_faction=Faction.IMPERIAL_NAVY,
        origin=Vector2D(x, y),
        max_range=max_range,
    )


def test_old_phantom_hit_no_longer_happens() -> None:
    # Ship reaches the salvo's path only at the end of the half, after the
    # salvo passed — the old end-position sweep called this a hit.
    target = _ship("t", x=-10.0, y=5.0, heading=90.0, speed=20.0)
    salvo = _salvo("s")

    impacts = advance_half([target], [salvo], DiceRoller(seed=1))

    assert impacts == []
    assert salvo.alive
    assert target.position.x == pytest.approx(0.0)


def test_old_phantom_miss_is_now_a_hit_at_the_right_instant() -> None:
    # Ship crosses the salvo's path mid-half and leaves; the old sweep
    # against the final position missed it.
    target = _ship("t", x=-5.0, y=10.0, heading=90.0, speed=20.0)
    salvo = _salvo("s")

    impacts = advance_half([target], [salvo], DiceRoller(seed=1))

    assert len(impacts) == 1
    # |r(τ)|² = 125 (1 − 2τ)² over the half → τ = 0.5 − HIT_RADIUS / (2√125)
    tau = 0.5 - HIT_RADIUS / (2 * math.sqrt(125.0))
    assert impacts[0].time == pytest.approx(0.5 * tau, abs=1e-9)
    assert impacts[0].position.x == pytest.approx(-5.0 + 10.0 * tau)
    assert impacts[0].position.y == pytest.approx(10.0)
    assert not salvo.alive


def test_second_half_impact_time_is_offset_into_turn() -> None:
    target = _ship("t", x=-5.0, y=10.0, heading=90.0, speed=20.0)
    salvo = _salvo("s")

    impacts = advance_half([target], [salvo], DiceRoller(seed=1), start=0.5)

    tau = 0.5 - HIT_RADIUS / (2 * math.sqrt(125.0))
    assert impacts[0].time == pytest.approx(0.5 + 0.5 * tau, abs=1e-9)


def test_salvo_past_max_range_at_impact_instant_misses() -> None:
    # The salvo stops at 8 GU; the ship only gets within reach after that.
    target = _ship("t", x=-5.0, y=10.0, heading=90.0, speed=20.0)
    salvo = _salvo("s", max_range=8.0 - HIT_RADIUS)

    assert advance_half([target], [salvo], DiceRoller(seed=1)) == []


def test_turning_ship_is_hit_on_its_curve() -> None:
    # 90° port curve during the half: the ship ends well off its straight line.
    probe = _ship("t", x=0.0, y=0.0, heading=90.0, speed=40.0, turn_rate=180.0)
    apply_move_orders([probe], {"t": MoveOrder(turn_degrees=-180.0)})
    drift_ship(probe, 0.5)
    arc_end = probe.position
    assert arc_end.distance_to(Vector2D(20.0, 0.0)) > 10.0

    def salvo() -> Projectile:
        # Flies west and reaches the arc end exactly at the end of the half.
        start = arc_end + heading_to_vector(90.0) * 20.0
        return _salvo("s", x=start.x, y=start.y, bearing=270.0)

    turning = _ship("t", x=0.0, y=0.0, heading=90.0, speed=40.0, turn_rate=180.0)
    apply_move_orders([turning], {"t": MoveOrder(turn_degrees=-180.0)})
    impacts = advance_half([turning], [salvo()], DiceRoller(seed=1))
    assert len(impacts) == 1
    assert 0.4 < impacts[0].time <= 0.5

    straight = _ship("t", x=0.0, y=0.0, heading=90.0, speed=40.0, turn_rate=180.0)
    assert advance_half([straight], [salvo()], DiceRoller(seed=1)) == []


def test_impacts_resolve_by_time_and_destroyed_ship_ignores_later_ones() -> None:
    target = _ship("t", x=0.0, y=10.0)
    target.shields_current = 0
    target.hull_current = 1
    # "a" sorts first by id but arrives later; "b" arrives first.
    late = _salvo("a", x=0.0, y=-10.0)
    early = _salvo("b", x=0.0, y=0.0)

    impacts = advance_half([target], [late, early], _AlwaysHitDice(seed=1))

    assert [i.projectile.id for i in impacts] == ["b"]
    assert not target.alive
    assert late.alive


def test_resolver_calls_phase_hook_five_times_with_mid_move_between_halves() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]
    ship = state.get_ship(ship_id)
    ship.speed = 0.0
    ship.heading = 0.0
    positions: dict[str, float] = {}
    names: list[str] = []

    def record(name: str, s: GameState) -> None:
        names.append(name)
        positions[name] = s.get_ship(ship_id).position.y

    cmd = Command(ship_id, "pass", {}, maneuver=Maneuver(speed=20.0))
    resolve_turn(state, {ship_id: cmd}, on_phase=record)

    assert names == ["start", "after_fire", "mid_move", "after_move", "end"]
    assert positions["mid_move"] - positions["after_fire"] == pytest.approx(10.0)
    assert positions["after_move"] - positions["after_fire"] == pytest.approx(20.0)


def test_maneuver_and_fire_in_one_command_both_happen() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]
    ship = state.get_ship(ship_id)
    ship.speed = 0.0
    ship.heading = 0.0
    cmd = Command(
        ship_id,
        "fire",
        {"slot": 3, "bearing": 0.0},
        maneuver=Maneuver(speed=10.0, turn=-30.0),
    )

    log = resolve_turn(state, {ship_id: cmd})

    assert any(isinstance(e, SalvoLaunchEvent) for e in log.events)
    assert ship.speed == 10.0
    assert ship.heading == pytest.approx(330.0)
    assert ship.pending_turn == 0.0


def test_resolver_impact_event_carries_time_and_position() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]
    target = state.get_ship(state.ai_ships[0])
    target.hull = replace(target.hull, speed=30.0)  # hulks cannot move
    target.position = Vector2D(-5.0, 10.0)
    target.heading = 90.0
    target.speed = 20.0
    salvo = _salvo("s")
    salvo.attacker_id = ship_id
    salvo.attacker_faction = state.get_ship(ship_id).faction
    state.projectiles.append(salvo)
    state.get_ship(ship_id).position = Vector2D(-60.0, -60.0)

    log = resolve_turn(state, {})

    impacts = [e for e in log.events if isinstance(e, SalvoImpactEvent)]
    assert len(impacts) == 1
    tau = 0.5 - HIT_RADIUS / (2 * math.sqrt(125.0))
    assert impacts[0].time == pytest.approx(0.5 * tau, abs=1e-9)
    assert impacts[0].position is not None
    assert impacts[0].position.x == pytest.approx(-5.0 + 10.0 * tau)
