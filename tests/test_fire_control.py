from __future__ import annotations

import pytest

from spacefleet.campaign.battle import build_battle
from spacefleet.combat.fire_control import (
    LOCK_SPREAD,
    UNLOCKED_SPREAD,
    bearing_spread,
    lock_level,
)
from spacefleet.commander.passive_skills import PassiveBus
from spacefleet.core.types import DetectionLevel, Vector2D
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
