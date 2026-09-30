from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from spacefleet.campaign.battle import BattleSession, build_battle
from spacefleet.core.types import Arc, DetectionLevel, Stance, Vector2D
from spacefleet.net.commands import Command, Maneuver
from spacefleet.net.turn_resolver import resolve_turn
from spacefleet.spatial.detection import ContactInfo
from spacefleet.spatial.geometry import arc_range_str, is_in_arc
from spacefleet.tui.model.orders import (
    Aim,
    OrderDraft,
    ability_order,
    blocker_summary,
    contact_aims,
    contact_blockers,
    finalize,
    fire_blocker,
    fire_unavailable_reason,
    hostile_contacts,
    predict_move,
    stance_rejection,
    validated_command,
    validated_fire_salvo,
    validated_maneuver,
)
from tests.campaign_helpers import campaign_state

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


def _session() -> BattleSession:
    return build_battle(campaign_state())


def _player_ship(session: BattleSession, index: int = 0) -> Ship:
    return session.state.ships[session.state.player_ships[session.player_id][index]]


def _contact(session: BattleSession, level: DetectionLevel) -> ContactInfo:
    target = session.state.ships[session.enemy_runtime_ids[0]]
    targetable = level is not DetectionLevel.BLIP
    return ContactInfo(
        ship=target,
        detection_level=level,
        true_distance=20.0,
        true_bearing=0.0,
        display_position=target.position if targetable else Vector2D(0.0, 100.0),
        display_name="Unknown contact" if not targetable else target.name,
        targetable=targetable,
        accuracy_penalty=level is DetectionLevel.CONTACT,
    )


def test_prow_arc_label_matches_the_actual_plus_or_minus_45_degree_rule() -> None:
    assert arc_range_str(Arc.PROW) == "315°–045° rel"
    assert is_in_arc(0, 315, Arc.PROW)
    assert is_in_arc(0, 45, Arc.PROW)
    assert not is_in_arc(0, 46, Arc.PROW)


def test_blip_contact_aims_do_not_reveal_runtime_id() -> None:
    session = _session()
    ship = _player_ship(session)
    aims = contact_aims(session, ship, _contact(session, DetectionLevel.BLIP))
    assert set(aims) == {mount.slot_id for mount in ship.weapons}
    assert all(aim.target_id is None for aim in aims.values())
    assert all(aim.lock is DetectionLevel.UNDETECTED for aim in aims.values())


@pytest.mark.parametrize("level", [DetectionLevel.CONTACT, DetectionLevel.IDENTIFIED])
def test_targetable_contact_aims_lock_on_runtime_id(level: DetectionLevel) -> None:
    session = _session()
    ship = _player_ship(session)
    target = session.state.ships[session.enemy_runtime_ids[0]]
    target.position = ship.position + Vector2D(5.0, 5.0)
    contact = _contact(session, level)
    aims = contact_aims(session, ship, contact)
    locked = [aim for aim in aims.values() if aim.bearing is not None]
    assert locked
    assert all(aim.target_id == contact.ship.id and aim.lock is level for aim in locked)


def test_hostile_contacts_excludes_far_enemies() -> None:
    session = _session()
    for enemy_id in session.enemy_runtime_ids:
        session.state.ships[enemy_id].position = Vector2D(10_000.0, 10_000.0)
    assert hostile_contacts(session, _player_ship(session)) == []


def test_fire_blocked_outside_arc_returns_reason() -> None:
    session = _session()
    ship = _player_ship(session)
    mount = next(
        m
        for m in ship.weapons
        if m.can_fire and any(not is_in_arc(0, b, m.arc) for b in range(360))
    )
    bearing = next(float(b) for b in range(360) if not is_in_arc(0, b, mount.arc))
    aim = Aim(bearing, None)

    blocker = fire_blocker(session, ship, mount.slot_id, aim=aim, used_slots=set())
    assert blocker is not None
    assert blocker[0] == "out of arc"
    reason = fire_unavailable_reason(session, ship, mount.slot_id, aim=aim, used_slots=set())
    assert reason is not None and reason.startswith("Unavailable:")

    salvo = validated_fire_salvo(session, ship, [{"slot": mount.slot_id, "bearing": bearing}])
    assert isinstance(salvo, str)


def test_fire_blocker_reports_queued_and_range() -> None:
    session = _session()
    ship = _player_ship(session)
    mount = next(m for m in ship.weapons if m.can_fire)
    bearing = next(float(b) for b in range(360) if is_in_arc(0, b, mount.arc))
    queued = fire_blocker(
        session, ship, mount.slot_id, aim=Aim(bearing, None), used_slots={mount.slot_id}
    )
    assert queued is not None and queued[0] == "queued"
    far = fire_blocker(
        session,
        ship,
        mount.slot_id,
        aim=Aim(bearing, mount.weapon.range + 1),
        used_slots=set(),
    )
    assert far is not None and far[0] == "out of range"
    near = fire_blocker(session, ship, mount.slot_id, aim=Aim(bearing, 1.0), used_slots=set())
    assert near is None


def test_contact_blockers_and_summary() -> None:
    session = _session()
    ship = _player_ship(session)
    contact = _contact(session, DetectionLevel.IDENTIFIED)
    every_slot = {mount.slot_id for mount in ship.weapons}
    blockers = contact_blockers(session, ship, contact, every_slot)
    assert set(blockers) == every_slot
    assert blocker_summary(blockers) == f"{len(every_slot)} queued"


def test_validated_command_returns_command_or_reason() -> None:
    session = _session()
    ship = _player_ship(session)
    command = validated_command(session, ship, ["pass"])
    assert isinstance(command, Command) and command.action == "pass"
    assert isinstance(validated_command(session, ship, ["ahead", "nan"]), str)
    assert isinstance(validated_command(session, ship, ["bogus"]), str)


def test_stance_rejection_reports_cooldown() -> None:
    session = _session()
    ship = _player_ship(session)
    other = next(stance for stance in Stance if stance is not ship.stance)
    assert stance_rejection(ship, ship.stance) is None
    assert stance_rejection(ship, other) is None
    ship.stance_cooldown_remaining = 2
    assert stance_rejection(ship, other) == "Locked for 2 more turn(s)."
    assert stance_rejection(ship, ship.stance) is None


def test_finalize_fills_pass_for_ships_without_orders() -> None:
    session = _session()
    first, second = (_player_ship(session, i) for i in range(2))
    fire = Command(first.id, "fire", {"slot": 1, "bearing": 0.0})
    draft = OrderDraft(commands={first.id: fire})

    result = finalize(draft, session)
    assert not isinstance(result, str)
    commands, stances, ability = result
    assert commands[first.id] is fire
    assert commands[second.id] == Command(ship_id=second.id, action="pass")
    assert stances == {}
    assert ability is None


def test_finalize_skips_dead_ships() -> None:
    session = _session()
    second = _player_ship(session, 1)
    second.take_hull_damage(second.hull_max)
    result = finalize(OrderDraft(), session)
    assert not isinstance(result, str)
    assert second.id not in result[0]


def test_finalize_rejects_stance_that_became_invalid() -> None:
    session = _session()
    ship = _player_ship(session)
    other = next(stance for stance in Stance if stance is not ship.stance)
    draft = OrderDraft(stances={ship.id: other})
    ship.stance_cooldown_remaining = 3

    result = finalize(draft, session)
    assert isinstance(result, str)
    assert ship.name in result
    assert "Locked for 3 more turn(s)." in result


@pytest.mark.parametrize(
    "maneuver",
    [
        None,
        Maneuver(speed=6.0),
        Maneuver(speed=0.0),
        Maneuver(turn=-40.0),
        Maneuver(speed=7.0, turn=15.0),
        Maneuver(speed=0.0, turn=90.0),
    ],
)
def test_predict_move_matches_resolution_without_mutating(maneuver: Maneuver | None) -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 4.0
    before = deepcopy(ship)

    prediction = predict_move(ship, maneuver, state=session.state)

    assert ship.position == before.position
    assert ship.heading == before.heading
    assert ship.speed == before.speed
    assert ship.pending_turn == before.pending_turn
    assert ship.combustion == before.combustion

    state = deepcopy(session.state)
    mids: list[tuple[Vector2D, float]] = []

    def on_phase(phase: str, phase_state: object) -> None:
        if phase == "mid_move":
            mid = state.ships[ship.id]
            mids.append((mid.position, mid.heading))

    command = Command(ship_id=ship.id, action="pass", maneuver=maneuver)
    resolve_turn(state, {ship.id: command}, {}, on_phase=on_phase)
    resolved = state.ships[ship.id]
    assert prediction.start == ship.position
    assert prediction.end.x == pytest.approx(resolved.position.x)
    assert prediction.end.y == pytest.approx(resolved.position.y)
    assert prediction.end_heading == pytest.approx(resolved.heading)
    (mid_pos, mid_heading) = mids[0]
    assert prediction.mid.x == pytest.approx(mid_pos.x)
    assert prediction.mid.y == pytest.approx(mid_pos.y)
    assert prediction.mid_heading == pytest.approx(mid_heading)
    assert prediction.path == [ship.position, prediction.mid, prediction.end]


def test_predict_move_clamps_turn_to_this_turns_limit() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 4.0
    limit = ship.max_turn_this_turn(4.0)

    prediction = predict_move(ship, Maneuver(turn=limit + 90.0), state=session.state)

    assert prediction.end_heading == pytest.approx((ship.heading + limit) % 360.0)


def test_validated_maneuver_enforces_turn_limit_at_new_speed() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 0.0
    pivot = ship.max_turn_this_turn(0.0)
    moving = ship.max_turn_this_turn(3.0)
    assert pivot > moving

    assert validated_maneuver(session, ship, None, pivot) == Maneuver(speed=None, turn=pivot)
    rejected = validated_maneuver(session, ship, 3.0, -pivot)
    assert isinstance(rejected, str)
    assert f"{moving:g}°" in rejected
    assert validated_maneuver(session, ship, 3.0, -moving) == Maneuver(speed=3.0, turn=-moving)


def test_finalize_carries_maneuver_alongside_the_action() -> None:
    session = _session()
    first, second = (_player_ship(session, i) for i in range(2))
    fire = Command(first.id, "fire", {"slot": 1, "bearing": 0.0})
    maneuver = Maneuver(speed=5.0, turn=15.0)
    draft = OrderDraft(
        commands={first.id: fire},
        maneuvers={first.id: maneuver, second.id: Maneuver(turn=-15.0)},
    )

    result = finalize(draft, session)
    assert not isinstance(result, str)
    commands = result[0]
    assert commands[first.id] == Command(first.id, "fire", fire.args, maneuver=maneuver)
    assert commands[second.id] == Command(second.id, "pass", maneuver=Maneuver(turn=-15.0))
    assert draft.commands[first.id].maneuver is None  # draft untouched


def test_finalize_without_maneuver_keeps_speed() -> None:
    session = _session()
    ship = _player_ship(session)
    ship.speed = 3.0
    result = finalize(OrderDraft(), session)
    assert not isinstance(result, str)
    command = result[0][ship.id]
    assert command.maneuver is None

    state = deepcopy(session.state)
    resolve_turn(state, result[0], {})
    assert state.ships[ship.id].speed == 3.0


def test_ability_order_unknown_id_is_rejected() -> None:
    session = _session()
    assert isinstance(ability_order(session, "no-such-ability"), str)


def test_action_parser_preserves_commands_and_rejects_nonfinite_numbers() -> None:
    from spacefleet.cli.action_parser import parse_action_command

    parsed = parse_action_command("ship-1", ["fire", "2", "90"])
    assert not isinstance(parsed, str)
    assert parsed["action"] == "fire"
    assert parsed["args"] == {"slot": 2, "bearing": 90.0}
    for tokens in (["ahead", "nan"], ["turn", "port", "inf"], ["fire", "1", "-inf"]):
        assert isinstance(parse_action_command("ship-1", tokens), str)


@pytest.mark.parametrize(
    ("faction_name", "ability_id"),
    [("IMPERIAL_NAVY", "micro_warp_jump"), ("CHAOS_FLEET", "warp_rift")],
)
def test_position_abilities_need_a_finite_position(faction_name: str, ability_id: str) -> None:
    from spacefleet.core.types import Faction

    session = build_battle(campaign_state(Faction[faction_name]))
    assert ability_order(session, ability_id) == "Choose a target position."
    nan = Vector2D(float("nan"), 0.0)
    assert ability_order(session, ability_id, target_position=nan) == "Coordinates must be finite."
    # A finite position passes targeting; only ownership/cooldown rules remain.
    result = ability_order(session, ability_id, target_position=Vector2D(12.5, -4.0))
    assert result not in ("Choose a target position.", "Coordinates must be finite.")


def test_cooldown_one_ability_remains_available_before_tick() -> None:
    from spacefleet.commander.commander import AbilityState

    session = _session()
    commander = session.state.fleets["player"].commander
    assert commander is not None
    commander.ability_state["concentrated_fire"] = AbilityState(1, cooldown_remaining=1)

    order = ability_order(session, "concentrated_fire", target_ship_id="player_ship_1")

    assert not isinstance(order, str)
    assert order.target_ship_id == "player_ship_1"
