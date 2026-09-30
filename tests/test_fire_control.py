from __future__ import annotations

import math

import pytest

from spacefleet.campaign.battle import build_battle
from spacefleet.combat.fire_control import (
    LOCK_SPREAD,
    UNLOCKED_SPREAD,
    bearing_spread,
    lead_solution,
    lock_level,
)
from spacefleet.combat.projectile_resolution import HIT_RADIUS
from spacefleet.commander.passive_skills import PassiveBus
from spacefleet.core.types import DetectionLevel, Vector2D, heading_to_vector
from spacefleet.net.commands import validate_command
from spacefleet.spatial.detection import compute_detection_level, effective_sensor_range
from tests.campaign_helpers import campaign_state


def _battle(*, sensor_mastery: bool = False):  # type: ignore[no-untyped-def]
    session = build_battle(campaign_state())
    state = session.state
    commander = state.fleet_of(state.ships[state.player_ships[session.player_id][0]]).commander
    assert commander is not None
    commander.passive_skill_ids = ["sensor_mastery"] if sensor_mastery else []
    state.passives = PassiveBus.build(state)
    shooter = state.ships[state.player_ships[session.player_id][0]]
    target = state.ships[session.enemy_runtime_ids[0]]
    return state, shooter, target


def test_sensor_mastery_extends_fleet_sensor_range_and_detection() -> None:
    state, shooter, target = _battle(sensor_mastery=True)
    base = shooter.hull.sensor_range
    assert effective_sensor_range(shooter, state) == base + 20.0

    target.position = Vector2D(shooter.position.x, shooter.position.y + base + 10.0)
    assert compute_detection_level(shooter, target) is DetectionLevel.BLIP
    assert compute_detection_level(shooter, target, state=state) is DetectionLevel.CONTACT


def test_sensor_mastery_tightens_bearing_spread() -> None:
    plain_state, plain_ship, _ = _battle()
    mastery_state, mastery_ship, _ = _battle(sensor_mastery=True)
    mount = plain_ship.weapons[0]

    assert bearing_spread(mastery_ship, mastery_ship.weapons[0], mastery_state) < (
        bearing_spread(plain_ship, mount, plain_state)
    )


def test_spread_widens_for_contact_and_unlocked_fire() -> None:
    state, shooter, _ = _battle()
    mount = shooter.weapons[0]
    identified = bearing_spread(shooter, mount, state, DetectionLevel.IDENTIFIED)

    assert bearing_spread(shooter, mount, state, DetectionLevel.CONTACT) == pytest.approx(
        identified * LOCK_SPREAD[DetectionLevel.CONTACT]
    )
    assert bearing_spread(shooter, mount, state, DetectionLevel.BLIP) == pytest.approx(
        identified * UNLOCKED_SPREAD
    )


def test_lock_level_follows_shared_detection_and_muzzle_flash() -> None:
    state, shooter, target = _battle()
    sensors = shooter.hull.sensor_range
    for ally in state.ships.values():
        if ally.faction == shooter.faction and ally is not shooter:
            ally.position = Vector2D(-500.0, -500.0)

    target.position = Vector2D(shooter.position.x, shooter.position.y + sensors * 0.5)
    assert lock_level(state, shooter, target.id) is DetectionLevel.IDENTIFIED

    target.position = Vector2D(shooter.position.x, shooter.position.y + sensors * 0.9)
    assert lock_level(state, shooter, target.id) is DetectionLevel.CONTACT

    target.position = Vector2D(shooter.position.x, shooter.position.y + sensors * 1.2)
    assert lock_level(state, shooter, target.id) is DetectionLevel.BLIP
    assert lock_level(state, shooter, target.id, {target.id}) is DetectionLevel.CONTACT

    assert lock_level(state, shooter, None) is DetectionLevel.UNDETECTED
    assert lock_level(state, shooter, shooter.id) is DetectionLevel.UNDETECTED


def test_fire_command_keeps_optional_target_and_rejects_bad_one() -> None:
    state, shooter, target = _battle()
    owners = state.owner_lookup()
    player = owners[shooter.id]
    raw = {"ship_id": shooter.id, "action": "fire", "args": {"slot": 3, "bearing": 0.0}}

    raw["args"]["target"] = target.id  # type: ignore[index]
    validated = validate_command(raw, shooter, player, owners)
    assert not isinstance(validated, str)
    assert validated.args["target"] == target.id

    raw["args"]["target"] = 7  # type: ignore[index]
    assert isinstance(validate_command(raw, shooter, player, owners), str)


def test_lead_on_stationary_target_aims_straight_at_it() -> None:
    origin = Vector2D(0.0, 0.0)
    target = Vector2D(30.0, 40.0)
    solution = lead_solution(origin, target, 90.0, 0.0, 20.0, 100.0)

    assert solution is not None
    assert solution.bearing == pytest.approx(math.degrees(math.atan2(30.0, 40.0)))
    assert solution.intercept_distance == pytest.approx(50.0)
    assert solution.time == pytest.approx(50.0 / 20.0)


def test_lead_on_crossing_target_meets_it_under_continuous_motion() -> None:
    origin = Vector2D(0.0, 0.0)
    target = Vector2D(-20.0, 40.0)
    heading, speed, shot_speed = 90.0, 12.0, 30.0  # target crosses west to east
    solution = lead_solution(origin, target, heading, speed, shot_speed, 200.0)

    assert solution is not None
    t = solution.time
    assert t > 0
    target_at_t = target + heading_to_vector(heading) * (speed * t)
    shot_at_t = origin + heading_to_vector(solution.bearing) * (shot_speed * t)
    assert shot_at_t.distance_to(target_at_t) < HIT_RADIUS * 0.01
    assert solution.intercept_distance == pytest.approx(shot_speed * t)
    # Leads east of the target's current bearing (~333°), toward where it goes.
    current = math.degrees(math.atan2(-20.0, 40.0)) % 360.0
    assert current < solution.bearing < 360.0


def test_lead_returns_none_when_target_outruns_projectile() -> None:
    solution = lead_solution(Vector2D(0.0, 0.0), Vector2D(0.0, 30.0), 0.0, 25.0, 20.0, 500.0)
    assert solution is None


def test_lead_returns_none_when_intercept_is_out_of_range() -> None:
    solution = lead_solution(Vector2D(0.0, 0.0), Vector2D(0.0, 80.0), 0.0, 5.0, 20.0, 90.0)
    assert solution is None
    in_range = lead_solution(Vector2D(0.0, 0.0), Vector2D(0.0, 80.0), 0.0, 5.0, 20.0, 120.0)
    assert in_range is not None
    assert in_range.intercept_distance == pytest.approx(80.0 / 15.0 * 20.0)
