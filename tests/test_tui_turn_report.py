"""End-of-turn report: per-ship damage and morale, under fog of war."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from spacefleet.combat.resolution import AttackResult
from spacefleet.core.types import DetectionLevel, Faction, Vector2D, WeaponType
from spacefleet.net.turn_resolver import (
    DestroyedEvent,
    LanceFireEvent,
    SalvoImpactEvent,
    TurnLog,
)
from spacefleet.tui.model.snapshot import PHASES, BattleSnapshot, ShipView
from spacefleet.tui.model.turn_report import build_turn_report, format_turn_report


def _view(
    ship_id: str,
    label: str,
    name: str,
    *,
    is_player: bool,
    detection: DetectionLevel = DetectionLevel.IDENTIFIED,
    alive: bool = True,
    morale: int | None = 10,
) -> ShipView:
    return ShipView(
        id=ship_id,
        label=label,
        name=name,
        faction=Faction.IMPERIAL_NAVY if is_player else Faction.CHAOS_FLEET,
        class_letter=label[0],
        position=Vector2D(0.0, 0.0),
        heading=0.0,
        detection=detection,
        is_player=is_player,
        alive=alive,
        morale=morale,
        morale_max=10 if morale is not None else None,
    )


def _snaps(start: list[ShipView], end: list[ShipView] | None = None) -> dict[str, BattleSnapshot]:
    end = start if end is None else end
    return {
        phase: BattleSnapshot(
            turn=3, phase=phase, ships=tuple(end if phase == "end" else start), projectiles=()
        )
        for phase in PHASES
    }


def _result(target: str, *, shields: int = 0, hull: int = 0) -> AttackResult:
    return AttackResult(
        attacker_name="x",
        weapon_name="w",
        weapon_type=WeaponType.BATTERY,
        target_name="y",
        distance=1.0,
        in_arc=True,
        in_range=True,
        target_ship_id=target,
        shield_blocked=shields,
        hull_damage_dealt=hull,
    )


def _ship(ship_id: str) -> Any:
    return SimpleNamespace(id=ship_id)


def _salvo(attacker: str, target: str, *, shields: int = 0, hull: int = 0) -> SalvoImpactEvent:
    proj: Any = SimpleNamespace(attacker_id=attacker, id=f"p-{attacker}", bearing=0.0)
    return SalvoImpactEvent(
        proj=proj, target=_ship(target), result=_result(target, shields=shields, hull=hull)
    )


def _lance(attacker: str, target: str, *, hull: int) -> LanceFireEvent:
    return LanceFireEvent(
        ship=_ship(attacker),
        weapon_name="Lance",
        bearing=0.0,
        result=_result(target, hull=hull),
    )


S1 = _view("s1", "S1", "Vengeful Starstorm", is_player=True)
S2 = _view("s2", "S2", "Iron Duke", is_player=True)
E1 = _view("e1", "E1", "Chaos Cruiser", is_player=False)


def _row(report: Any, ship_id: str) -> Any:
    return next(r for r in report.ships if r.ship_id == ship_id)


def test_report_sums_damage_dealt_and_taken_per_ship() -> None:
    log = TurnLog(
        turn=3,
        events=[
            _salvo("s1", "e1", shields=2, hull=1),
            _lance("s1", "e1", hull=2),
            _salvo("s2", "e1", shields=1, hull=0),
            _salvo("e1", "s1", shields=3, hull=2),
        ],
    )
    s1_end = _view("s1", "S1", "Vengeful Starstorm", is_player=True, morale=8)

    report = build_turn_report(_snaps([S1, S2, E1], [s1_end, S2, E1]), log, "player")

    assert report.turn == 3
    s1 = _row(report, "s1")
    assert (s1.damage_dealt, s1.shield_taken, s1.hull_taken) == (3, 3, 2)
    assert s1.shield_dealt == 2  # shield hits count as damage dealt too
    assert s1.morale_change == -2
    e1 = _row(report, "e1")
    assert (e1.damage_dealt, e1.shield_taken, e1.hull_taken) == (2, 3, 3)
    assert _row(report, "s2").damage_dealt == 0
    assert report.destroyed == ()
    text = "\n".join(format_turn_report(report))
    assert "Vengeful Starstorm [S1]" in text
    assert "Chaos Cruiser [E1]" in text
    assert "Dealt (shield / hull)" in text


def test_hidden_enemy_is_never_named() -> None:
    hidden = _view("e2", "?", "Unknown contact", is_player=False, detection=DetectionLevel.BLIP)
    log = TurnLog(
        turn=3, events=[_salvo("e2", "s1", shields=1, hull=2), _lance("e9", "s1", hull=1)]
    )

    report = build_turn_report(_snaps([S1, E1, hidden]), log, "player")

    ids = {r.ship_id for r in report.ships}
    assert "e2" not in ids and "e9" not in ids
    unknown = next(r for r in report.ships if r.ship_id is None)
    assert unknown.name == "unknown ship"
    assert unknown.damage_dealt == 3
    s1 = _row(report, "s1")
    assert (s1.shield_taken, s1.hull_taken) == (1, 3)
    text = "\n".join(format_turn_report(report))
    assert "Unknown contact" not in text
    assert "e2" not in text


def test_damage_to_a_hidden_ship_is_not_reported() -> None:
    log = TurnLog(turn=3, events=[_salvo("s1", "e7", shields=1, hull=4)])

    report = build_turn_report(_snaps([S1, E1]), log, "player")

    assert _row(report, "s1").damage_dealt == 0
    assert "e7" not in {r.ship_id for r in report.ships}


def test_destroyed_ships_are_listed_first() -> None:
    dead = _view("e1", "E1", "Chaos Cruiser", is_player=False, alive=False)
    log = TurnLog(
        turn=3,
        events=[
            _lance("s1", "e1", hull=6),
            DestroyedEvent(ship=_ship("e1"), killer_player="player"),
        ],
    )

    report = build_turn_report(_snaps([S1, E1], [S1, dead]), log, "player")

    assert report.destroyed == ("Chaos Cruiser [E1]",)
    assert _row(report, "e1").destroyed
    lines = format_turn_report(report)
    assert any("Destroyed: Chaos Cruiser [E1]" in line for line in lines[:3])


def test_quiet_turn_still_lists_visible_ships() -> None:
    report = build_turn_report(_snaps([S1, S2, E1]), TurnLog(turn=3), "player")

    assert [r.ship_id for r in report.ships] == ["s1", "s2", "e1"]
    assert all(r.damage_dealt == r.hull_taken == 0 for r in report.ships)
