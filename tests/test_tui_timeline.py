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
from spacefleet.tui.model.snapshot import PHASES, BattleSnapshot
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
    assert list(snaps) == list(PHASES)
    return snaps, log


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

    attacker = start.ship("p1_dauntless").label  # type: ignore[union-attr]
    target = start.ship("ai_hulk_1").label  # type: ignore[union-attr]
    line = f"{attacker} lance → {target}: 2 dmg"
    assert line not in tl.sample(lance.t0 - 0.01).log_lines
    assert line in tl.sample(lance.t0).log_lines


def test_lance_effect_progresses_while_active() -> None:
    _snaps, tl = _duel()
    (lance,) = _kinds(tl.tracks, "lance")
    frame = tl.sample((lance.t0 + lance.t1) / 2)
    (beam,) = [e for e in frame.effects if e.kind == "lance"]
    assert beam.progress == pytest.approx(0.5)
    assert not [e for e in tl.sample(lance.t1 + 0.01).effects if e.kind == "lance"]


def test_salvo_appears_at_launch_and_impacts_proportionally() -> None:
    _snaps, tl = _duel()
    (launch,) = _kinds(tl.tracks, "salvo_launch")
    pid = launch.payload["projectile_id"]
    assert pid is not None
    assert pid not in {p.id for p in tl.sample(launch.t0 - 0.01).projectiles}
    assert pid in {p.id for p in tl.sample(launch.t0).projectiles}

    m0, m1 = tl.windows["move"]
    (impact,) = [tr for tr in _kinds(tl.tracks, "impact") if tr.t0 >= m0]
    assert impact.payload["target_id"] == "ai_hulk_1"
    # Salvo travels 30 GU this move; the hulk sits ~22 GU down range.
    assert 0.5 < (impact.t0 - m0) / (m1 - m0) < 0.9
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
    assert any("unseen" in line for line in frame.log_lines)
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
    snaps, tl = _duel()
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
    label = after.label
    distance = before.position.distance_to(after.position)
    assert distance > 0.05

    m0, _m1 = tl.windows["move"]
    assert not any(label in line for line in tl.sample(m0 - 0.01).log_lines)
    lines = tl.sample(tl.duration).log_lines
    assert f"{label} speed 0 → 8 GU/turn" in lines
    assert f"{label} moved {distance:.1f} GU, heading {after.heading:.0f}°" in lines


def test_turn_order_is_logged() -> None:
    state = GameState.create_pve(["p1"], seed=7)
    turn = {"direction": "starboard", "degrees": 15.0}
    snaps, log = _run(state, {"p1_sword_1": Command("p1_sword_1", "turn", turn)})
    tl = TimelineBuilder(snaps, log, "p1").build()
    label = snaps["after_move"].ship("p1_sword_1").label  # type: ignore[union-attr]
    assert f"{label} turns starboard 15°" in tl.sample(tl.duration).log_lines


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
