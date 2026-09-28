"""Fog-of-war capture: ``snapshot_for`` shows only what the player's fleet sees."""

from __future__ import annotations

from dataclasses import fields

from spacefleet.core.types import DetectionLevel, Vector2D
from spacefleet.models.projectile import Projectile
from spacefleet.net.game_state import GameState
from spacefleet.tui.model.capture import snapshot_for

# create_pve("p1"): p1_dauntless (sensor 40) at origin, swords behind it
# (sensor 30, at y=-15 / y=-30).  Hulk distances below are from the Dauntless.
_BLIP_POS = Vector2D(0.0, 50.0)  # 40 < d <= 60
_CONTACT_POS = Vector2D(0.0, 35.0)  # 30 < d <= 40
_IDENT_POS = Vector2D(0.0, 20.0)  # d <= 30
_FAR_POS = Vector2D(0.0, 500.0)


def _state(hulk_1: Vector2D, hulk_2: Vector2D = _FAR_POS) -> GameState:
    state = GameState.create_pve(["p1"], seed=7)
    state.ships["ai_hulk_1"].position = hulk_1
    state.ships["ai_hulk_2"].position = hulk_2
    return state


def _projectile(state: GameState, pid: str, attacker_id: str, pos: Vector2D) -> Projectile:
    attacker = state.ships[attacker_id]
    return Projectile(
        id=pid,
        position=pos,
        bearing=90.0,
        speed=10.0,
        weapon_mount=state.ships["p1_dauntless"].weapons[0],
        attacker_id=attacker_id,
        attacker_name=attacker.name,
        attacker_faction=attacker.faction,
        origin=attacker.position,
        max_range=100.0,
    )


def test_own_ships_are_complete() -> None:
    state = _state(_FAR_POS)
    snap = snapshot_for(state, "p1", "start")
    assert snap.turn == state.turn
    assert snap.phase == "start"

    for i, sid in enumerate(state.player_ships["p1"]):
        ship = state.ships[sid]
        view = snap.ship(sid)
        assert view is not None
        assert view.is_player
        assert view.alive
        assert view.detection == DetectionLevel.IDENTIFIED
        assert view.position == ship.position
        assert view.heading == ship.heading
        assert view.name == ship.name
        assert view.hull == ship.hull_current
        assert view.hull_max == ship.hull_max
        assert view.shields == ship.shields_current
        assert view.shields_max == ship.shields_max
        assert view.morale == ship.morale
        assert view.morale_max == ship.morale_max
        assert view.stance == ship.stance
        assert view.label[1:] == str(i + 1)

    assert snap.ship("p1_dauntless").class_letter == "L"  # type: ignore[union-attr]
    assert snap.ship("p1_sword_1").class_letter == "E"  # type: ignore[union-attr]


def test_destroyed_own_ship_is_still_shown() -> None:
    state = _state(_FAR_POS)
    state.ships["p1_sword_2"].is_destroyed = True
    view = snapshot_for(state, "p1", "end").ship("p1_sword_2")
    assert view is not None
    assert not view.alive


def test_undetected_enemy_is_absent() -> None:
    state = _state(_FAR_POS, _FAR_POS)
    snap = snapshot_for(state, "p1", "start")
    assert snap.ship("ai_hulk_1") is None
    assert snap.ship("ai_hulk_2") is None


def test_blip_hides_heading_stats_and_true_position() -> None:
    state = _state(_BLIP_POS)
    true = state.ships["ai_hulk_1"]
    view = snapshot_for(state, "p1", "start").ship("ai_hulk_1")
    assert view is not None
    assert view.detection == DetectionLevel.BLIP
    assert view.heading is None
    assert view.label == "?"
    assert view.class_letter == "?"
    assert view.name == "Unknown contact"
    assert view.position != true.position
    assert view.position.distance_to(true.position) <= 10.0
    for attr in ("hull", "hull_max", "shields", "shields_max", "morale", "morale_max", "stance"):
        assert getattr(view, attr) is None


def test_blip_leaks_no_true_position_field() -> None:
    state = _state(_BLIP_POS)
    true = state.ships["ai_hulk_1"].position
    view = snapshot_for(state, "p1", "start").ship("ai_hulk_1")
    assert view is not None
    for f in fields(view):
        value = getattr(view, f.name)
        assert value != true
        if isinstance(value, float):
            assert value not in (true.x, true.y)
    assert view.position.x != true.x
    assert view.position.y != true.y


def test_blip_jitter_is_stable_within_a_turn() -> None:
    state = _state(_BLIP_POS)
    a = snapshot_for(state, "p1", "start").ship("ai_hulk_1")
    b = snapshot_for(state, "p1", "after_move").ship("ai_hulk_1")
    assert a is not None and b is not None
    assert a.position == b.position

    state.turn += 1
    c = snapshot_for(state, "p1", "start").ship("ai_hulk_1")
    assert c is not None
    assert c.position != a.position


def test_contact_shows_heading_and_class_but_no_stats() -> None:
    state = _state(_CONTACT_POS)
    true = state.ships["ai_hulk_1"]
    view = snapshot_for(state, "p1", "start").ship("ai_hulk_1")
    assert view is not None
    assert view.detection == DetectionLevel.CONTACT
    assert view.position == true.position
    assert view.heading == true.heading
    assert view.class_letter == "E"
    assert view.label == "E1"
    assert view.name == "Escort-class"
    assert not view.is_player
    assert view.hull is None
    assert view.stance is None


def test_identified_shows_name_and_stats() -> None:
    state = _state(_IDENT_POS, _CONTACT_POS)
    true = state.ships["ai_hulk_1"]
    snap = snapshot_for(state, "p1", "start")
    view = snap.ship("ai_hulk_1")
    assert view is not None
    assert view.detection == DetectionLevel.IDENTIFIED
    assert view.name == true.name
    assert view.hull == true.hull_current
    assert view.shields == true.shields_current
    assert view.morale == true.morale
    assert view.stance == true.stance
    assert view.label == "E1"
    assert snap.ship("ai_hulk_2").label == "E2"  # type: ignore[union-attr]


def test_destroyed_enemy_only_when_contact_or_better() -> None:
    state = _state(_CONTACT_POS, _BLIP_POS)
    state.ships["ai_hulk_1"].is_destroyed = True
    state.ships["ai_hulk_2"].is_destroyed = True
    snap = snapshot_for(state, "p1", "end")
    dead = snap.ship("ai_hulk_1")
    assert dead is not None and not dead.alive
    assert snap.ship("ai_hulk_2") is None


def test_dead_observers_do_not_see() -> None:
    state = _state(_IDENT_POS)
    for sid in state.player_ships["p1"]:
        state.ships[sid].is_destroyed = True
    assert snapshot_for(state, "p1", "end").ship("ai_hulk_1") is None


def test_capture_does_not_consume_game_dice() -> None:
    reference = _state(_BLIP_POS)
    expected = [reference.dice.uniform(0.0, 1.0) for _ in range(5)]

    state = _state(_BLIP_POS)
    snapshot_for(state, "p1", "start")
    snapshot_for(state, "p1", "end")
    assert [state.dice.uniform(0.0, 1.0) for _ in range(5)] == expected


def test_projectiles_filtered_by_sensor_range() -> None:
    state = _state(_FAR_POS, _CONTACT_POS)
    state.projectiles = [
        _projectile(state, "near_own", "p1_dauntless", Vector2D(5.0, 5.0)),
        _projectile(state, "near_hidden", "ai_hulk_1", Vector2D(0.0, 10.0)),
        _projectile(state, "near_contact", "ai_hulk_2", Vector2D(0.0, 30.0)),
        _projectile(state, "far", "p1_dauntless", Vector2D(0.0, 300.0)),
    ]
    snap = snapshot_for(state, "p1", "after_fire")
    by_id = {p.id: p for p in snap.projectiles}
    assert set(by_id) == {"near_own", "near_hidden", "near_contact"}
    assert by_id["near_own"].attacker_id == "p1_dauntless"
    assert by_id["near_hidden"].attacker_id is None
    assert by_id["near_contact"].attacker_id == "ai_hulk_2"
    assert by_id["near_own"].bearing == 90.0


def test_dead_projectiles_are_omitted() -> None:
    state = _state(_FAR_POS)
    proj = _projectile(state, "spent", "p1_dauntless", Vector2D(5.0, 5.0))
    proj.alive = False
    state.projectiles = [proj]
    assert snapshot_for(state, "p1", "end").projectiles == ()


def test_label_memo_keeps_enemy_labels_stable() -> None:
    state = _state(_IDENT_POS, _CONTACT_POS)
    labels: dict[str, str] = {}
    first = snapshot_for(state, "p1", "start", labels=labels)
    assert first.ship("ai_hulk_1").label == "E1"  # type: ignore[union-attr]
    assert first.ship("ai_hulk_2").label == "E2"  # type: ignore[union-attr]

    # hulk_1 drops out of detection; without the memo hulk_2 would become "E1".
    state.ships["ai_hulk_1"].position = _FAR_POS
    second = snapshot_for(state, "p1", "end", labels=labels)
    assert second.ship("ai_hulk_1") is None
    assert second.ship("ai_hulk_2").label == "E2"  # type: ignore[union-attr]
    assert labels == {"ai_hulk_1": "E1", "ai_hulk_2": "E2"}


def test_label_memo_skips_blips_and_takes_next_free_number() -> None:
    state = _state(_BLIP_POS, _CONTACT_POS)
    labels: dict[str, str] = {}
    snap = snapshot_for(state, "p1", "start", labels=labels)
    assert snap.ship("ai_hulk_1").label == "?"  # type: ignore[union-attr]
    assert snap.ship("ai_hulk_2").label == "E1"  # type: ignore[union-attr]

    state.ships["ai_hulk_1"].position = _IDENT_POS
    snap = snapshot_for(state, "p1", "end", labels=labels)
    assert snap.ship("ai_hulk_1").label == "E2"  # type: ignore[union-attr]
    assert snap.ship("ai_hulk_2").label == "E1"  # type: ignore[union-attr]
