"""Turn playback timeline built from real phase snapshots and a real TurnLog."""

from __future__ import annotations

from dataclasses import replace

import pytest

from spacefleet.commander.abilities import AbilityUsedEvent
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import LANCE_2
from spacefleet.dice import DiceRoller
from spacefleet.net import turn_resolver
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import TurnLog, resolve_turn
from spacefleet.phases.command_phase import AbilityRejectedEvent
from spacefleet.spatial.geometry import bearing_from_to, relative_bearing_360
from spacefleet.tui.model.capture import snapshot_for
from spacefleet.tui.model.snapshot import PHASES, BattleSnapshot, ShipView
from spacefleet.tui.model.timeline import Timeline, TimelineBuilder, Track

_FAR = Vector2D(0.0, 500.0)
_LONG_LANCE = replace(LANCE_2, range=200.0)


class _AlwaysHitDice(DiceRoller):
    def roll_d6(self, count: int) -> list[int]:
        return [6] * count


@pytest.fixture(autouse=True)
def _no_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turn_resolver, "bearing_spread", lambda *_args: 0.0)


def _run(
    state: GameState, commands: dict[str, Command], observer: str = "p1"
) -> tuple[dict[str, BattleSnapshot], TurnLog]:
    snaps: dict[str, BattleSnapshot] = {}
    labels: dict[str, str] = {}

    def capture(name: str, s: GameState) -> None:
        snaps[name] = snapshot_for(s, observer, name, labels=labels)

    log = resolve_turn(state, commands, on_phase=capture)
    # "mid_move" is optional: older resolvers report a single move step.
    assert list(snaps) in (list(PHASES), [p for p in PHASES if p != "mid_move"])
    return snaps, log


def _without_mid(snaps: dict[str, BattleSnapshot]) -> dict[str, BattleSnapshot]:
    return {phase: snap for phase, snap in snaps.items() if phase != "mid_move"}


def _with_mid(
    snaps: dict[str, BattleSnapshot], positions: dict[str, Vector2D]
) -> dict[str, BattleSnapshot]:
    """Snapshots with a synthetic ``mid_move``: after_fire moved to *positions*."""
    base = snaps["after_fire"]
    ships = tuple(
        replace(s, position=positions[s.id]) if s.id in positions else s for s in base.ships
    )
    mid = BattleSnapshot(base.turn, "mid_move", ships, base.projectiles)
    out = _without_mid(snaps)
    return {phase: out[phase] if phase != "mid_move" else mid for phase in PHASES}


def _who(view: ShipView | None) -> str:
    assert view is not None
    return f"{view.name} [{view.label}]"


def _duel_state() -> GameState:
    """p1 lances hulk_1 dead ahead, a Sword shoots a salvo at it, another Sword moves."""
    state = GameState.create_pve(["p1"], seed=7)
    state.dice = _AlwaysHitDice(seed=1)
    state.ships["ai_hulk_1"].position = Vector2D(0.0, 20.0)
    state.ships["ai_hulk_2"].position = _FAR
    state.ships["p1_dauntless"].weapons[2].weapon = LANCE_2  # slot 3, prow
    state.ships["p1_sword_1"].position = Vector2D(-10.0, 0.0)
    return state


def _duel_commands() -> dict[str, Command]:
    salvo_bearing = bearing_from_to(Vector2D(-10.0, 0.0), Vector2D(0.0, 20.0))
    return {
        "p1_dauntless": Command("p1_dauntless", "fire", {"slot": 3, "bearing": 0.0}),
        "p1_sword_1": Command("p1_sword_1", "fire", {"slot": 1, "bearing": salvo_bearing}),
        "p1_sword_2": Command("p1_sword_2", "ahead", {"speed": 20.0}),
    }


def _duel() -> tuple[dict[str, BattleSnapshot], Timeline]:
    snaps, log = _run(_duel_state(), _duel_commands())
    return snaps, TimelineBuilder(snaps, log, "p1").build()


def _kinds(tracks: tuple[Track, ...], kind: str) -> list[Track]:
    return [tr for tr in tracks if tr.kind == kind]


def _hidden_lancer_state() -> GameState:
    """An undetected hulk far to the east lances the Dauntless."""
    state = GameState.create_pve(["p1"], seed=7)
    state.dice = _AlwaysHitDice(seed=1)
    state.ships["ai_hulk_1"].position = _FAR
    hulk = state.ships["ai_hulk_2"]
    hulk.position = Vector2D(150.0, 0.0)
    hulk.weapons[0].weapon = _LONG_LANCE
    return state


def _aim(state: GameState, shooter_id: str, target_id: str) -> Command:
    shooter = state.ships[shooter_id]
    absolute = bearing_from_to(shooter.position, state.ships[target_id].position)
    bearing = relative_bearing_360(shooter.heading, absolute)
    return Command(shooter_id, "fire", {"slot": 1, "bearing": bearing})


# ── Structure ───────────────────────────────────────────────────


def test_windows_are_contiguous_in_phase_order_and_tracks_sorted() -> None:
    _snaps, tl = _duel()
    w = tl.windows
    assert list(w) == ["command", "fire", "move", "end"]
    assert w["command"] == (0.0, 0.4)
    assert w["fire"] == (0.4, 1.6)
    assert w["move"] == (1.6, 3.4)
    assert w["end"] == (3.4, 4.2)
    assert tl.duration == pytest.approx(4.2)

    starts = [tr.t0 for tr in tl.tracks]
    assert starts == sorted(starts)
    assert all(0.0 <= tr.t0 <= tr.t1 <= tl.duration for tr in tl.tracks)

    (lance,) = _kinds(tl.tracks, "lance")
    assert w["fire"][0] <= lance.t0 < w["fire"][1]
    impacts = _kinds(tl.tracks, "impact")
    assert any(w["move"][0] < tr.t0 < w["move"][1] for tr in impacts)


def test_sample_zero_is_start_and_duration_is_end() -> None:
    snaps, tl = _duel()
    first = tl.sample(0.0)
    assert first.ships == snaps["start"].ships
    assert first.projectiles == snaps["start"].projectiles
    assert tl.sample(-3.0).ships == first.ships

    last = tl.sample(tl.duration)
    end = snaps["end"]
    assert last.ships == end.ships
    assert last.projectiles == end.projectiles
    assert tl.sample(tl.duration + 5.0).ships == end.ships
    for view in end.ships:
        if view.is_player:
            bars = last.bars[view.id]
            assert (bars.hull, bars.shields, bars.morale) == (view.hull, view.shields, view.morale)
            assert bars.hull_max == view.hull_max


def test_ships_interpolate_during_move_window() -> None:
    snaps, tl = _duel()
    m0, m1 = tl.windows["move"]
    before = snaps["after_fire"].ship("p1_sword_2")
    after = snaps["after_move"].ship("p1_sword_2")
    assert before is not None and after is not None
    assert before.position.y != after.position.y

    assert tl.sample(m0 - 0.01).ships == tl.sample(0.0).ships
    mid = next(s for s in tl.sample((m0 + m1) / 2).ships if s.id == "p1_sword_2")
    lo, hi = sorted((before.position.y, after.position.y))
    assert lo < mid.position.y < hi


def test_lance_hit_yields_beam_impact_damage_text_and_log() -> None:
    snaps, tl = _duel()
    start = snaps["after_fire"]
    (lance,) = _kinds(tl.tracks, "lance")
    assert lance.payload["attacker_id"] == "p1_dauntless"
    assert lance.payload["target_id"] == "ai_hulk_1"
    assert lance.payload["hit"] is True
    assert lance.payload["from"] == start.ship("p1_dauntless").position  # type: ignore[union-attr]
    assert lance.payload["to"] == start.ship("ai_hulk_1").position  # type: ignore[union-attr]

    hits = [tr for tr in _kinds(tl.tracks, "impact") if tr.t0 < tl.windows["move"][0]]
    assert [tr.payload["target_id"] for tr in hits] == ["ai_hulk_1"]
    assert hits[0].payload["damage"] == 2
    texts = [tr for tr in _kinds(tl.tracks, "damage_text") if tr.t0 == hits[0].t0]
    assert texts and texts[0].payload["text"] == "-2"

    target = start.ship("ai_hulk_1")
    assert target is not None and target.hull is not None and target.hull_max is not None
    hull = snaps["start"].ship("ai_hulk_1").hull  # type: ignore[union-attr]
    line = (
        f"{_who(start.ship('p1_dauntless'))} lance hits {_who(target)}: "
        f"2 hull damage (hull {hull - 2}/{target.hull_max})"  # type: ignore[operator]
    )
    assert line not in tl.sample(lance.t0 - 0.01).log_lines
    assert line in tl.sample(lance.t0).log_lines


def test_lance_effect_progresses_while_active() -> None:
    _snaps, tl = _duel()
    (lance,) = _kinds(tl.tracks, "lance")
    frame = tl.sample((lance.t0 + lance.t1) / 2)
    (beam,) = [e for e in frame.effects if e.kind == "lance"]
    assert beam.progress == pytest.approx(0.5)
    assert not [e for e in tl.sample(lance.t1 + 0.01).effects if e.kind == "lance"]


def test_salvo_appears_at_launch_and_impacts_at_the_event_time() -> None:
    snaps, log = _run(_duel_state(), _duel_commands())
    tl = TimelineBuilder(snaps, log, "p1").build()
    (launch,) = _kinds(tl.tracks, "salvo_launch")
    pid = launch.payload["projectile_id"]
    assert pid is not None
    assert pid not in {p.id for p in tl.sample(launch.t0 - 0.01).projectiles}
    assert pid in {p.id for p in tl.sample(launch.t0).projectiles}

    m0, m1 = tl.windows["move"]
    (impact,) = [tr for tr in _kinds(tl.tracks, "impact") if tr.t0 >= m0]
    assert impact.payload["target_id"] == "ai_hulk_1"
    # Impacts land at SalvoImpactEvent.time, mapped onto the move window.
    event = next(e for e in log.events if isinstance(e, turn_resolver.SalvoImpactEvent))
    assert 0.0 < event.time < 1.0
    assert impact.t0 == pytest.approx(m0 + event.time * (m1 - m0))
    assert pid in {p.id for p in tl.sample(impact.t0 - 0.01).projectiles}
    assert pid not in {p.id for p in tl.sample(impact.t0 + 0.01).projectiles}


def test_bars_change_at_event_time() -> None:
    snaps, log = _run(_hidden_lancer_state(), {"ai_hulk_2": _aim_hidden()})
    tl = TimelineBuilder(snaps, log, "p1").build()
    start = snaps["start"].ship("p1_dauntless")
    hit = snaps["after_fire"].ship("p1_dauntless")
    assert start is not None and hit is not None
    assert (hit.hull, hit.shields) != (start.hull, start.shields)

    (impact,) = _kinds(tl.tracks, "impact")
    before = tl.sample(impact.t0).bars["p1_dauntless"]
    assert (before.hull, before.shields) == (start.hull, start.shields)
    ramps = [tr for tr in _kinds(tl.tracks, "bar") if tr.payload["ship_id"] == "p1_dauntless"]
    settled = tl.sample(max(tr.t1 for tr in ramps if tr.t0 < tl.windows["move"][0]))
    after = settled.bars["p1_dauntless"]
    assert (after.hull, after.shields) == (hit.hull, hit.shields)


# ── Fog of war ──────────────────────────────────────────────────


def _aim_hidden() -> Command:
    return _aim(_hidden_lancer_state(), "ai_hulk_2", "p1_dauntless")


def test_hidden_attacker_yields_incoming_marker_but_no_beam() -> None:
    snaps, log = _run(_hidden_lancer_state(), {"ai_hulk_2": _aim_hidden()})
    assert snaps["after_fire"].ship("ai_hulk_2") is None
    tl = TimelineBuilder(snaps, log, "p1").build()

    assert _kinds(tl.tracks, "lance") == []
    (impact,) = _kinds(tl.tracks, "impact")
    assert impact.payload["target_id"] == "p1_dauntless"
    (incoming,) = _kinds(tl.tracks, "incoming_fire")
    assert incoming.payload == {"target_id": "p1_dauntless", "bearing": 90.0}

    frame = tl.sample(incoming.t0)
    assert frame.incoming == (("p1_dauntless", 90.0),)
    dauntless = snaps["after_fire"].ship("p1_dauntless")
    assert dauntless is not None
    damage = impact.payload["damage"]
    hull = snaps["start"].ship("p1_dauntless").hull  # type: ignore[union-attr]
    line = (  # the Dauntless's single shield point stops the first hit
        f"unknown ship lance hits {_who(dauntless)}: 1 blocked by shields, "
        f"{damage} hull damage "
        f"(hull {hull - damage}/{dauntless.hull_max})"
    )
    assert line in frame.log_lines
    assert not any("Hulk" in ln or "hulk" in ln for ln in frame.log_lines)
    assert all("ai_hulk_2" not in str(tr.payload) for tr in tl.tracks)


def test_event_with_no_visible_end_is_dropped() -> None:
    state = GameState.create_pve(["p1", "p2"], seed=7)
    state.dice = _AlwaysHitDice(seed=1)
    for i, sid in enumerate(state.player_ships["p2"]):
        state.ships[sid].position = Vector2D(500.0 + 10.0 * i, 500.0)
    for sid in state.ai_ships:
        state.ships[sid].position = Vector2D(-500.0, -500.0)
    hulk = state.ships["ai_hulk_1"]
    hulk.position = Vector2D(500.0, 600.0)
    hulk.weapons[0].weapon = _LONG_LANCE
    command = _aim(state, "ai_hulk_1", "p2_dauntless")

    snaps, log = _run(state, {"ai_hulk_1": command})
    assert any(isinstance(e, turn_resolver.LanceFireEvent) for e in log.events)
    tl = TimelineBuilder(snaps, log, "p1").build()

    visual = {"lance", "impact", "damage_text", "incoming_fire"}
    assert [tr for tr in tl.tracks if tr.kind in visual] == []
    assert not any("lance" in line for line in tl.sample(tl.duration).log_lines)


def test_ability_banner_only_for_own_fleet() -> None:
    snaps, log = _run(_duel_state(), _duel_commands())
    log.events[:0] = [
        AbilityUsedEvent(ability_id="broadside", fleet_id="p1"),
        AbilityRejectedEvent(ability_id="warp", fleet_id="ai_ai_hulk_1", reason="no charges"),
    ]
    tl = TimelineBuilder(snaps, log, "p1").build()
    (ability,) = _kinds(tl.tracks, "ability")
    assert ability.payload["ability_id"] == "broadside"
    assert tl.windows["command"][0] <= ability.t0 < tl.windows["command"][1]
    assert not any("warp" in line for line in tl.sample(tl.duration).log_lines)


# ── Staggering ──────────────────────────────────────────────────


def test_many_shots_stagger_and_stretch_the_fire_window() -> None:
    state = _duel_state()
    shots = [{"slot": 3, "bearing": 0.0} for _ in range(12)]
    commands = {"p1_dauntless": Command("p1_dauntless", "fire", {"shots": shots})}
    snaps, log = _run(state, commands)
    tl = TimelineBuilder(snaps, log, "p1").build()

    beams = _kinds(tl.tracks, "lance")
    assert len(beams) == 12
    gaps = [b.t0 - a.t0 for a, b in zip(beams, beams[1:], strict=False)]
    assert gaps == pytest.approx([0.15] * 11)

    f0, f1 = tl.windows["fire"]
    assert f1 - f0 > 1.2
    assert beams[-1].t1 <= f1
    assert tl.windows["move"][0] == f1
    assert tl.duration == pytest.approx(f1 + 1.8 + 0.8)
    assert tl.sample(tl.duration).ships == snaps["end"].ships


# ── Movement: trails and log ────────────────────────────────────


def _movement_only() -> tuple[dict[str, BattleSnapshot], Timeline]:
    state = GameState.create_pve(["p1"], seed=7)
    state.ships["p1_sword_1"].speed = 0.0
    commands = {"p1_sword_1": Command("p1_sword_1", "ahead", {"speed": 8.0})}
    snaps, log = _run(state, commands)
    return snaps, TimelineBuilder(snaps, log, "p1").build()


def test_trails_follow_moving_ship_through_move_window() -> None:
    snaps, log = _run(_duel_state(), _duel_commands())
    snaps = _without_mid(snaps)
    tl = TimelineBuilder(snaps, log, "p1").build()
    m0, m1 = tl.windows["move"]
    before = snaps["after_fire"].ship("p1_sword_2")
    after = snaps["after_move"].ship("p1_sword_2")
    assert before is not None and after is not None

    assert tl.sample(0.0).trails == {}
    assert tl.sample(m0 - 0.01).trails == {}

    start, current = tl.sample((m0 + m1) / 2).trails["p1_sword_2"]
    assert start == before.position
    lo, hi = sorted((before.position.y, after.position.y))
    assert lo < current.y < hi

    end = snaps["end"].ship("p1_sword_2")
    assert end is not None
    assert tl.sample(tl.duration).trails["p1_sword_2"] == (before.position, end.position)


def test_stationary_ship_has_no_trail() -> None:
    snaps, tl = _duel()
    a = snaps["after_fire"].ship("p1_dauntless")
    b = snaps["after_move"].ship("p1_dauntless")
    assert a is not None and b is not None and a.position == b.position
    m0, m1 = tl.windows["move"]
    assert "p1_dauntless" not in tl.sample((m0 + m1) / 2).trails
    assert "p1_dauntless" not in tl.sample(tl.duration).trails


def test_hidden_enemy_movement_leaves_no_trail_or_log() -> None:
    state = _hidden_lancer_state()
    commands = {"ai_hulk_2": Command("ai_hulk_2", "ahead", {"speed": 10.0})}
    snaps, log = _run(state, commands)
    assert any(
        isinstance(e, turn_resolver.DriftEvent) and e.ship.id == "ai_hulk_2" for e in log.events
    )
    assert snaps["after_fire"].ship("ai_hulk_2") is None
    assert snaps["after_move"].ship("ai_hulk_2") is None
    tl = TimelineBuilder(snaps, log, "p1").build()

    m0, m1 = tl.windows["move"]
    for t in ((m0 + m1) / 2, tl.duration):
        assert "ai_hulk_2" not in tl.sample(t).trails
    assert all("ai_hulk_2" not in str(tr.payload) for tr in tl.tracks)
    assert not any("moved" in line or "speed" in line for line in tl.sample(tl.duration).log_lines)


def test_movement_only_turn_logs_speed_and_drift() -> None:
    snaps, tl = _movement_only()
    before = snaps["after_fire"].ship("p1_sword_1")
    after = snaps["after_move"].ship("p1_sword_1")
    assert before is not None and after is not None
    mid = snaps.get("mid_move", snaps["after_fire"]).ship("p1_sword_1")
    assert mid is not None
    distance = before.position.distance_to(mid.position) + mid.position.distance_to(after.position)
    assert distance > 0.05

    m0, _m1 = tl.windows["move"]
    assert not any(after.label in line for line in tl.sample(m0 - 0.01).log_lines)
    lines = [ln for ln in tl.sample(tl.duration).log_lines if _who(after) in ln]
    assert lines == [
        f"{_who(after)} speed 0 → 8, moved {distance:.1f} GU, heading {after.heading:.0f}°"
    ]


def test_turn_order_is_logged() -> None:
    state = GameState.create_pve(["p1"], seed=7)
    turn = {"direction": "starboard", "degrees": 15.0}
    snaps, log = _run(state, {"p1_sword_1": Command("p1_sword_1", "turn", turn)})
    tl = TimelineBuilder(snaps, log, "p1").build()
    after = snaps["after_move"].ship("p1_sword_1")
    assert after is not None and after.heading is not None
    line = f"{_who(after)} turns 15° starboard, heading {after.heading:.0f}°"
    assert line in tl.sample(tl.duration).log_lines


def test_fully_absorbed_hit_reads_shield_not_minus_zero() -> None:
    from spacefleet.core.types import DetectionLevel, Faction
    from spacefleet.tui.model import timeline
    from spacefleet.tui.model.snapshot import ShipView

    target = ShipView(
        id="s1",
        label="S1",
        name="S1",
        faction=Faction.IMPERIAL_NAVY,
        class_letter="S",
        position=Vector2D(0.0, 0.0),
        heading=0.0,
        detection=DetectionLevel.IDENTIFIED,
        is_player=True,
        alive=True,
    )
    texts = [
        tr.payload["text"] for tr in timeline._impact(1.0, target, 0) if tr.kind == "damage_text"
    ]
    assert texts == ["shield"]
    texts = [
        tr.payload["text"] for tr in timeline._impact(1.0, target, 3) if tr.kind == "damage_text"
    ]
    assert texts == ["-3"]


# ── mid_move keyframe ───────────────────────────────────────────


def _curved_duel() -> tuple[dict[str, BattleSnapshot], Timeline, Vector2D]:
    """Duel with a synthetic mid_move that bends p1_sword_2's path east."""
    snaps, log = _run(_duel_state(), _duel_commands())
    a = snaps["after_fire"].ship("p1_sword_2")
    b = snaps["after_move"].ship("p1_sword_2")
    assert a is not None and b is not None
    bend = Vector2D((a.position.x + b.position.x) / 2 + 6.0, (a.position.y + b.position.y) / 2)
    snaps = _with_mid(snaps, {"p1_sword_2": bend})
    return snaps, TimelineBuilder(snaps, log, "p1").build(), bend


def _at(tl: Timeline, t: float, ship_id: str) -> Vector2D:
    return next(s.position for s in tl.sample(t).ships if s.id == ship_id)


def test_motion_passes_through_mid_move_at_half_of_move_window() -> None:
    snaps, tl, bend = _curved_duel()
    a = snaps["after_fire"].ship("p1_sword_2")
    b = snaps["after_move"].ship("p1_sword_2")
    assert a is not None and b is not None
    m0, m1 = tl.windows["move"]

    half = _at(tl, (m0 + m1) / 2, "p1_sword_2")
    assert (half.x, half.y) == pytest.approx((bend.x, bend.y))
    quarter = _at(tl, m0 + (m1 - m0) / 4, "p1_sword_2")
    assert quarter.x == pytest.approx((a.position.x + bend.x) / 2)
    assert quarter.y == pytest.approx((a.position.y + bend.y) / 2)
    late = _at(tl, m0 + 3 * (m1 - m0) / 4, "p1_sword_2")
    assert late.x == pytest.approx((bend.x + b.position.x) / 2)
    assert late.y == pytest.approx((bend.y + b.position.y) / 2)


def test_without_mid_move_motion_is_one_straight_leg() -> None:
    snaps, log = _run(_duel_state(), _duel_commands())
    snaps = _without_mid(snaps)
    tl = TimelineBuilder(snaps, log, "p1").build()
    a = snaps["after_fire"].ship("p1_sword_2")
    b = snaps["after_move"].ship("p1_sword_2")
    assert a is not None and b is not None
    m0, m1 = tl.windows["move"]
    half = _at(tl, (m0 + m1) / 2, "p1_sword_2")
    assert half.x == pytest.approx((a.position.x + b.position.x) / 2)
    assert half.y == pytest.approx((a.position.y + b.position.y) / 2)


def test_trail_bends_through_mid_move_once_passed() -> None:
    snaps, tl, bend = _curved_duel()
    a = snaps["after_fire"].ship("p1_sword_2")
    end = snaps["end"].ship("p1_sword_2")
    assert a is not None and end is not None
    m0, m1 = tl.windows["move"]

    early = tl.sample(m0 + (m1 - m0) / 4).trails["p1_sword_2"]
    assert len(early) == 2 and early[0] == a.position
    late = tl.sample(m0 + 3 * (m1 - m0) / 4).trails["p1_sword_2"]
    assert late[:2] == (a.position, bend) and len(late) == 3
    assert tl.sample(tl.duration).trails["p1_sword_2"] == (a.position, bend, end.position)


# ── Salvo impact timing ─────────────────────────────────────────


def test_salvo_impact_lands_at_event_time_and_position() -> None:
    snaps, log = _run(_duel_state(), _duel_commands())
    where = Vector2D(1.5, 19.0)
    for i, ev in enumerate(log.events):
        if isinstance(ev, turn_resolver.SalvoImpactEvent):
            log.events[i] = replace(ev, time=0.3, position=where)
            pid = ev.proj.id
    tl = TimelineBuilder(snaps, log, "p1").build()

    m0, m1 = tl.windows["move"]
    (impact,) = [tr for tr in _kinds(tl.tracks, "impact") if tr.t0 >= m0]
    assert impact.t0 == pytest.approx(m0 + 0.3 * (m1 - m0))
    assert impact.payload["position"] == where
    (text,) = [tr for tr in _kinds(tl.tracks, "damage_text") if tr.t0 == impact.t0]
    assert text.payload["position"] == where
    assert pid in {p.id for p in tl.sample(impact.t0 - 0.01).projectiles}
    assert pid not in {p.id for p in tl.sample(impact.t0 + 0.01).projectiles}


# ── Full log text ───────────────────────────────────────────────


def test_salvo_launch_and_impact_text() -> None:
    snaps, log = _run(_duel_state(), _duel_commands())
    tl = TimelineBuilder(snaps, log, "p1").build()
    launch = next(e for e in log.events if isinstance(e, turn_resolver.SalvoLaunchEvent))
    impact = next(e for e in log.events if isinstance(e, turn_resolver.SalvoImpactEvent))
    sword = snaps["after_fire"].ship("p1_sword_1")
    hulk = snaps["after_move"].ship("ai_hulk_1")
    assert hulk is not None and hulk.hull_max is not None
    r = impact.result
    hull = snaps["after_fire"].ship("ai_hulk_1").hull  # type: ignore[union-attr]
    assert hull is not None

    lines = tl.sample(tl.duration).log_lines
    assert f"{_who(sword)} fires {launch.weapon_name} at {_who(hulk)}" in lines
    assert (
        f"Salvo hits {_who(hulk)}: {r.raw_hits} hits, {r.shield_blocked} blocked by shields, "
        f"{r.armor_saves} saved by armour, {r.hull_damage_dealt} hull damage "
        f"(hull {max(0, hull - r.hull_damage_dealt)}/{hulk.hull_max})"
    ) in lines


def test_destroyed_names_the_last_attacker() -> None:
    state = _duel_state()
    snaps, log = _run(state, _duel_commands())
    log.events.append(
        turn_resolver.DestroyedEvent(ship=state.ships["ai_hulk_1"], killer_player="p1")
    )
    tl = TimelineBuilder(snaps, log, "p1").build()
    hulk = snaps["end"].ship("ai_hulk_1")
    sword = snaps["end"].ship("p1_sword_1")
    assert f"{_who(hulk)} destroyed by {_who(sword)}" in tl.sample(tl.duration).log_lines


def test_destroyed_by_hidden_ship_reads_unknown_ship() -> None:
    state = _hidden_lancer_state()
    snaps, log = _run(state, {"ai_hulk_2": _aim_hidden()})
    log.events.append(
        turn_resolver.DestroyedEvent(ship=state.ships["p1_dauntless"], killer_player=None)
    )
    tl = TimelineBuilder(snaps, log, "p1").build()
    dauntless = snaps["end"].ship("p1_dauntless")
    assert f"{_who(dauntless)} destroyed by unknown ship" in tl.sample(tl.duration).log_lines


def test_lance_miss_text() -> None:
    state = _duel_state()
    state.ships["ai_hulk_1"].position = _FAR
    snaps, log = _run(state, _duel_commands())
    tl = TimelineBuilder(snaps, log, "p1").build()
    dauntless = snaps["after_fire"].ship("p1_dauntless")
    assert f"{_who(dauntless)} lance misses" in tl.sample(tl.duration).log_lines


def test_lance_absorbed_by_shields_says_so() -> None:
    state = _duel_state()
    state.ships["ai_hulk_1"].shields_current = 1
    snaps, log = _run(state, _duel_commands())
    tl = TimelineBuilder(snaps, log, "p1").build()
    lines = [ln for ln in tl.sample(tl.duration).log_lines if "lance hits" in ln]
    assert lines and "1 blocked by shields" in lines[0]
