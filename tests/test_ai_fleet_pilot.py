"""AI fleet pilot — controlled-ship selection and targeting."""

from __future__ import annotations

import dataclasses

import pytest

from spacefleet.core.types import Arc, Faction, Stance, Vector2D
from spacefleet.data.demo_data import HULK_HULL, SALVAGE_GUN
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.models.weapon import WeaponMount
from spacefleet.net.ai_controller import AIController
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import SalvoImpactEvent, resolve_turn
from spacefleet.spatial.geometry import distance

# The HULK hull is immobile (speed/turn_rate 0) with a wide DORSAL gun — useless
# for testing maneuver/arc logic. Build a mobile ship with a narrow PROW weapon.
_MOBILE_HULL = dataclasses.replace(HULK_HULL, speed=20.0, turn_rate=45.0, hull_hits=8)
_PROW_GUN = WeaponMount(slot_id=1, slot_name="Gun", arc=Arc.PROW, weapon=SALVAGE_GUN)


def _ship(sid: str, faction: Faction, pos: Vector2D, heading: float = 0.0) -> Ship:
    hull = dataclasses.replace(_MOBILE_HULL, faction=faction)
    s = Ship.from_profile(
        sid, sid, hull, [dataclasses.replace(_PROW_GUN)], position=pos, heading=heading
    )
    s.faction = faction
    return s


def _state(*ships: Ship) -> GameState:
    state = GameState(dice=DiceRoller(seed=1))
    for s in ships:
        state.ships[s.id] = s
    return state


def test_controlled_ids_restricts_commands() -> None:
    a = _ship("a", Faction.CHAOS_FLEET, Vector2D(0, 0))
    b = _ship("b", Faction.CHAOS_FLEET, Vector2D(5, 0))
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 100))
    state = _state(a, b, enemy)
    ai = AIController()
    cmds = ai.generate_commands(state, controlled_ids=["a"])
    assert set(cmds.keys()) == {"a"}


def test_default_controls_ai_ships() -> None:
    hulk = _ship("ai_hulk_1", Faction.CHAOS_FLEET, Vector2D(0, 0))
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 100))
    state = _state(hulk, enemy)
    state.ai_ships.append("ai_hulk_1")
    ai = AIController()
    cmds = ai.generate_commands(state)
    assert set(cmds.keys()) == {"ai_hulk_1"}


def test_fires_when_enemy_in_arc_and_range() -> None:
    # Hulk weapons fire forward (prow); enemy dead ahead (north = heading 0).
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    state = _state(atk, enemy)
    ai = AIController()
    cmd = ai.generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.action == "fire"
    assert cmd.args["slot"] == atk.weapons[0].slot_id
    assert abs(cmd.args["bearing"] - 0.0) < 1.0  # bearing to due-north target
    # Fires and maneuvers in the same turn: close-in and ahead → hold position.
    assert cmd.maneuver is not None
    assert cmd.maneuver.speed == 0.0
    assert cmd.maneuver.turn == 0.0


def test_prefers_shields_down_target_in_solution() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    shielded = _ship("shield", Faction.IMPERIAL_NAVY, Vector2D(0, 2))
    exposed = _ship("exposed", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    exposed.shields_current = 0
    shielded.shields_current = max(1, shielded.shields_current)
    ai = AIController()
    target = ai._choose_target(atk, [shielded, exposed])
    assert target.id == "exposed"


def test_skips_disabled_weapon() -> None:
    # A weapon crit set can_fire=False; _validate_fire would reject firing it, so
    # the AI must not treat it as a firing solution. Enemy dead ahead, in range.
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    atk.weapons[0].can_fire = False
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    state = _state(atk, enemy)
    ai = AIController()
    assert ai._firing_solution(atk, enemy) is None
    cmd = ai.generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.action == "pass"
    assert cmd.maneuver is not None


def test_choose_target_falls_back_to_in_solution_tier() -> None:
    # Two enemies in firing solution (prow, in range) but shields up, plus a
    # nearest enemy out of arc (not in solution). Target must be in-solution,
    # never the closer out-of-solution one.
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    sol_a = _ship("sol_a", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    sol_b = _ship("sol_b", Faction.IMPERIAL_NAVY, Vector2D(0, 4))
    sol_a.shields_current = max(1, sol_a.shields_current)
    sol_b.shields_current = max(1, sol_b.shields_current)
    # Nearest enemy, but off the starboard beam (out of the PROW arc).
    out = _ship("out", Faction.IMPERIAL_NAVY, Vector2D(1, 0))
    ai = AIController()
    assert ai._firing_solution(atk, out) is None
    target = ai._choose_target(atk, [sol_a, sol_b, out])
    assert target.id in {"sol_a", "sol_b"}


def test_turns_toward_enemy_outside_arc() -> None:
    # Enemy off the starboard side (east), ship facing north → must turn starboard.
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(50, 0))
    state = _state(atk, enemy)
    cmd = AIController().generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.action == "pass"
    assert cmd.maneuver is not None
    assert cmd.maneuver.speed is None  # keeps current speed while turning
    assert 0 < cmd.maneuver.turn <= atk.max_turn_this_turn(atk.speed)  # + = starboard


def test_turn_toward_enemy_to_port_is_negative_and_clamped() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    atk.speed = 10.0
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(-50, -50))  # 225°: far to port
    state = _state(atk, enemy)
    cmd = AIController().generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.maneuver is not None
    assert cmd.maneuver.turn == -atk.max_turn_this_turn(10.0)


def test_stationary_ship_pivots_up_to_its_pivot_limit() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    atk.speed = 0.0
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, -50))  # dead astern
    state = _state(atk, enemy)
    cmd = AIController().generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.maneuver is not None
    assert abs(cmd.maneuver.turn) == pytest.approx(min(180.0, atk.max_turn_this_turn(0.0)))


def test_closes_distance_when_far_and_ahead() -> None:
    # Enemy far but dead ahead (in arc, out of range) → accelerate.
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 500))
    state = _state(atk, enemy)
    cmd = AIController().generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.action == "pass"
    assert cmd.maneuver is not None
    assert cmd.maneuver.speed == atk.effective_speed_max > 0
    assert cmd.maneuver.turn == 0.0


def test_braces_when_crippled() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    atk.hull_current = 1  # well below 40% of max
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    state = _state(atk, enemy)
    AIController().generate_commands(state, controlled_ids=["atk"])
    assert atk.stance == Stance.BRACE_FOR_IMPACT


def test_locks_on_when_engaging_healthy() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 3))  # within best range
    state = _state(atk, enemy)
    AIController().generate_commands(state, controlled_ids=["atk"])
    assert atk.stance == Stance.LOCK_ON


def _sep(state: GameState) -> float:
    """Distance between the two fleet flagships (imp[0] vs cha[0])."""
    imp = state.ships[state.player_ships["imp"][0]]
    cha = state.ships[state.player_ships["cha"][0]]
    return distance(imp.position, cha.position)


# Integration smoke for the greedy AI-vs-AI battle. The greedy pilot fires the
# best-bearing weapon at the nearest enemy but does not lead its shots, so it
# can't reliably hit a maneuvering target — a battle may run for many turns
# without producing fleet casualties unless both sides close to point-blank.
# We therefore assert the AI *converges* (fleets close distance) and that it
# *fires live ordnance that resolves* (a SalvoImpactEvent occurs), rather than
# asserting fleet-on-fleet kills.
def test_ai_fleet_drives_battle_forward() -> None:
    state = GameState.create_mixed(["imp"], ["cha"], ships_per_player=2, seed=7)
    ai = AIController()
    start_sep = _sep(state)
    impacts = 0
    for _ in range(12):
        alive = [sid for sid, ship in state.ships.items() if ship.alive]
        cmds = ai.generate_commands(state, controlled_ids=alive)
        log = resolve_turn(state, cmds)
        impacts += sum(1 for e in log.events if isinstance(e, SalvoImpactEvent))
        if state.is_game_over():
            break

    # 1. Maneuver works: the two flagships converge over the run.
    assert _sep(state) < start_sep
    # 2. Combat is live (no mechanical stalemate): the AI fires and projectiles
    #    resolve to impact at least once.
    assert impacts >= 1
