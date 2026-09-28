from __future__ import annotations

from dataclasses import replace

import pytest

from spacefleet.combat.fire_control import aim_for
from spacefleet.core.types import Arc, DetectionLevel, Vector2D
from spacefleet.data.demo_data import LANCE_2
from spacefleet.dice import DiceRoller
from spacefleet.models.weapon import WeaponMount
from spacefleet.net import turn_resolver
from spacefleet.net.ai_controller import AIController
from spacefleet.net.commands import Command, validate_command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import (
    LanceFireEvent,
    SalvoImpactEvent,
    SalvoLaunchEvent,
    resolve_turn,
)


class _AlwaysHitDice(DiceRoller):
    def roll_d6(self, count: int) -> list[int]:
        return [6] * count


@pytest.fixture
def no_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turn_resolver, "bearing_spread", lambda *_args: 0.0)


@pytest.mark.usefixtures("no_spread")
def test_multiple_fire_shots_resolve_in_declared_order_with_distinct_bearings() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]
    command = Command(
        ship_id=ship_id,
        action="fire",
        args={
            "shots": [
                {"slot": 2, "bearing": 90.0},
                {"slot": 1, "bearing": 270.0},
            ]
        },
    )

    log = resolve_turn(state, {ship_id: command})

    launches = [event for event in log.events if isinstance(event, SalvoLaunchEvent)]
    assert [(event.weapon_name, event.bearing) for event in launches] == [
        (state.get_ship(ship_id).weapons[1].weapon.name, 90.0),
        (state.get_ship(ship_id).weapons[0].weapon.name, 270.0),
    ]
    assert ship_id in state.fired_this_turn


@pytest.mark.usefixtures("no_spread")
def test_legacy_single_fire_resolves_unchanged() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]
    command = Command(
        ship_id=ship_id,
        action="fire",
        args={"slot": 3, "bearing": 0.0},
    )

    log = resolve_turn(state, {ship_id: command})

    fires = [event for event in log.events if isinstance(event, SalvoLaunchEvent)]
    assert len(fires) == 1
    assert fires[0].bearing == 0.0


def test_mixed_salvo_continues_after_lance_destroys_its_target() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]
    ship = state.get_ship(ship_id)
    ship.weapons[2].weapon = LANCE_2
    target = state.get_ship(state.ai_ships[0])
    target.position = Vector2D(ship.position.x, ship.position.y + 10)
    target.shields_current = 0
    target.hull_current = 1
    state.dice = _AlwaysHitDice(seed=1)
    command = Command(
        ship_id=ship_id,
        action="fire",
        args={
            "shots": [
                {"slot": 3, "bearing": 0.0},
                {"slot": 2, "bearing": 90.0},
            ]
        },
    )

    log = resolve_turn(state, {ship_id: command})

    fire_events = [
        event for event in log.events if isinstance(event, (LanceFireEvent, SalvoLaunchEvent))
    ]
    assert [type(event) for event in fire_events] == [LanceFireEvent, SalvoLaunchEvent]
    lance = fire_events[0]
    assert isinstance(lance, LanceFireEvent)
    assert lance.result is not None
    assert lance.result.target_destroyed
    assert not target.alive


def _moving_target_duel(lead: bool) -> tuple[GameState, list[SalvoImpactEvent]]:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship = state.get_ship(state.player_ships["player"][0])
    ship.position = Vector2D(0.0, 0.0)
    ship.heading = 0.0
    ship.speed = 0.0
    target = state.get_ship(state.ai_ships[0])
    target.hull = replace(target.hull, speed=30.0)
    target.position = Vector2D(35.0, 5.0)
    target.heading = 0.0
    target.speed = 20.0
    target.pending_turn = 0.0
    mount = next(m for m in ship.weapons if m.weapon.speed > 0 and m.arc.value == "starboard")
    if lead:
        solution = aim_for(ship, mount, target, target.position)
        assert solution is not None
        bearing = solution.bearing
    else:
        bearing = 90.0 - 8.13  # straight at the target's current position
    command = Command(ship.id, "fire", {"slot": mount.slot_id, "bearing": bearing})
    impacts: list[SalvoImpactEvent] = []
    for turn in range(3):
        log = resolve_turn(state, {ship.id: command} if turn == 0 else {})
        impacts.extend(e for e in log.events if isinstance(e, SalvoImpactEvent))
    return state, impacts


@pytest.mark.usefixtures("no_spread")
def test_lead_solution_hits_target_holding_course_in_real_resolver() -> None:
    _state, impacts = _moving_target_duel(lead=True)
    assert len(impacts) == 1


@pytest.mark.usefixtures("no_spread")
def test_aiming_at_current_position_misses_moving_target() -> None:
    _state, impacts = _moving_target_duel(lead=False)
    assert impacts == []


def test_battery_launch_bearing_is_scattered_by_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turn_resolver, "bearing_spread", lambda *_args: 3.0)
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["player"][0]

    log = resolve_turn(state, {ship_id: Command(ship_id, "fire", {"slot": 3, "bearing": 0.0})})

    fires = [event for event in log.events if isinstance(event, SalvoLaunchEvent)]
    assert fires[0].bearing != 0.0
    assert min(fires[0].bearing, 360.0 - fires[0].bearing) < 15.0


def test_resolver_spread_uses_lock_on_declared_target(monkeypatch: pytest.MonkeyPatch) -> None:
    locks: list[DetectionLevel] = []

    def _spy(_ship, _mount, _state, lock):  # type: ignore[no-untyped-def]
        locks.append(lock)
        return 0.0

    monkeypatch.setattr(turn_resolver, "bearing_spread", _spy)
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship = state.get_ship(state.player_ships["player"][0])
    target = state.get_ship(state.ai_ships[0])
    target.position = Vector2D(ship.position.x, ship.position.y + 10)

    resolve_turn(
        state,
        {
            ship.id: Command(
                ship.id,
                "fire",
                {
                    "shots": [
                        {"slot": 1, "bearing": 270.0},
                        {"slot": 3, "bearing": 0.0, "target": target.id},
                    ]
                },
            )
        },
    )

    assert locks == [DetectionLevel.UNDETECTED, DetectionLevel.IDENTIFIED]


@pytest.mark.usefixtures("no_spread")
def test_fire_bearing_is_relative_to_prow() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ship = state.get_ship(state.player_ships["player"][0])
    ship.heading = 126.0
    starboard = next(m for m in ship.weapons if m.arc.value == "starboard")
    owners = state.owner_lookup()

    # The reported case: heading 126°, starboard battery at 90° rel is in arc.
    ok = validate_command(
        {"ship_id": ship.id, "action": "fire", "args": {"slot": starboard.slot_id, "bearing": 90}},
        ship,
        "player",
        owners,
    )
    assert isinstance(ok, Command)
    bad = validate_command(
        {"ship_id": ship.id, "action": "fire", "args": {"slot": starboard.slot_id, "bearing": 0}},
        ship,
        "player",
        owners,
    )
    assert bad == "Bearing 0° rel is outside starboard arc (045°–135° rel)."

    log = resolve_turn(state, {ship.id: ok})

    (launch,) = [e for e in log.events if isinstance(e, SalvoLaunchEvent)]
    assert launch.bearing == pytest.approx(90.0)
    (proj,) = state.projectiles
    assert proj.bearing == pytest.approx(216.0)


def test_ai_fire_orders_are_prow_relative_and_valid() -> None:
    state = GameState.create_pve(["player"], ships_per_player=1, seed=1)
    ai_ship = state.get_ship(state.ai_ships[0])
    player = state.get_ship(state.player_ships["player"][0])
    ai_ship.position = Vector2D(0.0, 0.0)
    ai_ship.heading = 200.0
    player.position = Vector2D(0.0, -15.0)  # absolute 180°: 20° off the port bow
    player.speed = 0.0
    ai_ship.weapons = [
        WeaponMount(slot_id=1, slot_name="Prow", arc=Arc.PROW, weapon=LANCE_2),
    ]

    command = AIController().generate_commands(state, [ai_ship.id])[ai_ship.id]

    assert command.action == "fire"
    assert command.args["bearing"] == pytest.approx(340.0)
