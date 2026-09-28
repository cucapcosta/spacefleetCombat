"""TacticalMap widget: pure glyph helper plus Pilot-driven behaviour."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from textual.app import App, ComposeResult
from textual.pilot import Pilot

from spacefleet.core.types import DetectionLevel, Faction, Vector2D
from spacefleet.tui.model.snapshot import BattleSnapshot, ProjectileView, ShipView
from spacefleet.tui.model.timeline import Effect, Frame
from spacefleet.tui.widgets.tactical_map import TacticalMap, heading_glyph


@pytest.mark.parametrize(
    ("heading", "glyph"),
    [
        (0, "▲"),
        (22, "▲"),
        (23, "◥"),
        (45, "◥"),
        (90, "▶"),
        (135, "◢"),
        (180, "▼"),
        (225, "◣"),
        (270, "◀"),
        (315, "◤"),
        (337, "◤"),
        (338, "▲"),
        (350, "▲"),
        (360, "▲"),
        (-90, "◀"),
    ],
)
def test_heading_glyph_octants(heading: float, glyph: str) -> None:
    assert heading_glyph(heading) == glyph


def _ship(
    ship_id: str,
    label: str,
    pos: Vector2D,
    *,
    faction: Faction = Faction.IMPERIAL_NAVY,
    heading: float | None = 0.0,
    is_player: bool = True,
    alive: bool = True,
    detection: DetectionLevel = DetectionLevel.IDENTIFIED,
) -> ShipView:
    return ShipView(
        id=ship_id,
        label=label,
        name=label,
        faction=faction,
        class_letter=label[0],
        position=pos,
        heading=heading,
        detection=detection,
        is_player=is_player,
        alive=alive,
    )


SHIPS = (
    _ship("p1", "C1", Vector2D(0, 0), heading=90.0),
    _ship("p2", "E2", Vector2D(20, 10), heading=180.0),
    _ship(
        "e1",
        "?",
        Vector2D(60, 30),
        faction=Faction.CHAOS_FLEET,
        heading=None,
        is_player=False,
        detection=DetectionLevel.BLIP,
    ),
    _ship("e2", "L1", Vector2D(-30, 40), faction=Faction.CHAOS_FLEET, is_player=False),
)
SNAPSHOT = BattleSnapshot(
    turn=1,
    phase="start",
    ships=SHIPS,
    projectiles=(ProjectileView("t1", Vector2D(10, 20), 45.0, "p1"),),
)


class MapApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.ship_clicks: list[str] = []
        self.map_clicks: list[Vector2D] = []

    def compose(self) -> ComposeResult:
        yield TacticalMap()

    def on_tactical_map_ship_clicked(self, message: TacticalMap.ShipClicked) -> None:
        self.ship_clicks.append(message.ship_id)

    def on_tactical_map_map_clicked(self, message: TacticalMap.MapClicked) -> None:
        self.map_clicks.append(message.world_pos)


Scenario = Callable[[MapApp, TacticalMap, Pilot[None]], Awaitable[None]]


def _run(scenario: Scenario, size: tuple[int, int] = (80, 30)) -> None:
    async def go() -> None:
        app = MapApp()
        async with app.run_test(size=size) as pilot:
            tmap = app.query_one(TacticalMap)
            tmap.focus()
            tmap.show_snapshot(SNAPSHOT)
            await pilot.pause()
            await scenario(app, tmap, pilot)

    asyncio.run(go())


def _text(tmap: TacticalMap) -> str:
    return "\n".join(line.plain for line in tmap.render_lines_text())


def test_snapshot_renders_ship_glyphs_and_labels() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        text = _text(tmap)
        assert "▶" in text  # p1 heading 90
        assert "C1" in text
        assert "▼" in text  # p2 heading 180
        assert "?" in text  # blip
        assert "•" in text  # projectile
        assert "GU" in text  # scale bar

    _run(scenario)


def test_destroyed_ship_shows_cross() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        dead = _ship("p1", "C1", Vector2D(0, 0), alive=False)
        tmap.show_snapshot(BattleSnapshot(1, "end", (dead,), ()))
        assert "✕" in _text(tmap)

    _run(scenario)


def test_click_on_ship_posts_ship_clicked() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        col, row = tmap.camera.world_to_cell(Vector2D(20, 10))
        await pilot.click(TacticalMap, offset=(col, row))
        await pilot.pause()
        assert app.ship_clicks == ["p2"]
        assert app.map_clicks == []

    _run(scenario)


def test_click_on_empty_space_posts_map_clicked() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        await pilot.click(TacticalMap, offset=(1, 1))
        await pilot.pause()
        assert app.ship_clicks == []
        assert len(app.map_clicks) == 1
        expected = tmap.camera.dot_to_world(3, 6)
        assert app.map_clicks[0].distance_to(expected) < 1e-6

    _run(scenario)


def _all_visible(tmap: TacticalMap) -> bool:
    cam = tmap.camera
    for ship in SHIPS:
        dx, dy = cam.world_to_dot(ship.position)
        if not (0 <= dx < cam.dot_width and 0 <= dy < cam.dot_height):
            return False
    return True


def test_fit_all_frames_every_ship() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        tmap.camera.center = Vector2D(5000, 5000)
        tmap.camera.gu_per_dot = 0.01
        assert not _all_visible(tmap)
        await pilot.press("f")  # letters belong to the order panel now
        assert not _all_visible(tmap)
        tmap.fit_all()
        assert _all_visible(tmap)

    _run(scenario)


def test_zoom_and_pan_keys_move_camera() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        gu = tmap.camera.gu_per_dot
        await pilot.press("plus")
        assert tmap.camera.gu_per_dot < gu
        center = tmap.camera.center
        await pilot.press("l")
        assert tmap.camera.center.x > center.x
        await pilot.press("up")
        assert tmap.camera.center.y > center.y

    _run(scenario)


def test_zoom_keys_can_be_disabled() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        tmap.set_zoom_keys_enabled(False)
        gu = tmap.camera.gu_per_dot
        await pilot.press("plus", "minus")
        assert tmap.camera.gu_per_dot == gu

    _run(scenario)


def test_center_on_selected_ship() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        tmap.select("e2", center=False)
        tmap.center_on_selected()
        assert tmap.camera.center == Vector2D(-30, 40)

    _run(scenario)


def test_overlays_toggle_and_change_output() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        tmap.select("p1")
        tmap.set_overlay_data(
            "p1",
            arcs=[(45.0, 135.0, 30.0, "yellow"), (0.0, 360.0, 10.0, "blue")],
            sensor=(50.0, 30.0, 15.0),
            drift=(90.0, Vector2D(8, 0)),
        )
        before = _text(tmap)
        for overlay in ("arcs", "sensor", "drift"):
            tmap.toggle_overlay(overlay)
            after = _text(tmap)
            assert after != before
            before = after
        assert tmap.overlays == {"arcs", "sensor", "drift"}
        tmap.toggle_overlay("arcs")
        assert "arcs" not in tmap.overlays

    _run(scenario)


def test_previews_render_and_clear() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        base = _text(tmap)
        previews: list[tuple[str, object]] = [
            ("route", [Vector2D(0, 0), Vector2D(5, 5), Vector2D(10, 5)]),
            ("route", {"path": [Vector2D(0, 0), Vector2D(0, 10)], "heading": 0.0}),
            ("aim", (Vector2D(0, 0), 45.0, 10.0, 40.0)),
            ("strike", ["e2"]),
            ("strike", {"targets": ["e2"]}),
            (
                "aim",
                {"origin": Vector2D(0, 0), "bearing_abs": 45.0, "spread_deg": 10.0, "range": 40.0},
            ),
        ]
        for kind, data in previews:
            tmap.set_preview(kind, data)
            assert _text(tmap) != base
            tmap.clear_preview()
            assert _text(tmap) == base

    _run(scenario)


def test_show_frame_with_every_effect_kind() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        a, b = Vector2D(0, 0), Vector2D(20, 10)
        effects = [
            Effect("lance", 0.1, {"from": a, "to": b}),
            Effect("impact", 0.2, {"position": b}),
            Effect("damage_text", 0.5, {"position": b, "text": "-3"}),
            Effect("explosion", 0.5, {"position": b}),
            Effect("salvo_launch", 0.3, {"position": a}),
            Effect("strike", 0.4, {"from": a, "to": b}),
            Effect("incoming_fire", 0.4, {"target_id": "p1", "bearing": 200.0}),
            Effect("mystery", 0.5, {}),
            Effect("lance", 0.5, {}),
            Effect("damage_text", 0.5, {"position": "nope"}),
        ]
        for progress in (0.0, 0.5, 1.0):
            frame = Frame(
                t=progress,
                ships=SHIPS,
                projectiles=SNAPSHOT.projectiles,
                effects=tuple(Effect(e.kind, progress, e.payload) for e in effects),
                log_lines=(),
                bars={},
                incoming=(("p1", 270.0), ("ghost", 10.0)),
            )
            tmap.show_frame(frame)
            await pilot.pause()
            assert _text(tmap)

    _run(scenario)


def test_damage_text_visible_at_start() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        frame = Frame(
            t=0.0,
            ships=SHIPS,
            projectiles=(),
            effects=(Effect("damage_text", 0.0, {"position": Vector2D(0, 0), "text": "-7"}),),
            log_lines=(),
            bars={},
        )
        tmap.show_frame(frame)
        assert "-7" in _text(tmap)

    _run(scenario)


def test_resize_updates_camera() -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        assert (tmap.camera.cols, tmap.camera.rows) == (tmap.size.width, tmap.size.height)
        await pilot.resize_terminal(60, 20)
        await pilot.pause()
        assert (tmap.camera.cols, tmap.camera.rows) == (60, 20)

    _run(scenario)


def test_disabled_zoom_keys_reach_app_bindings() -> None:
    class SpeedApp(App[None]):
        BINDINGS = [("plus", "speed", "Speed")]

        def __init__(self) -> None:
            super().__init__()
            self.speed_presses = 0

        def compose(self) -> ComposeResult:
            yield TacticalMap()

        def action_speed(self) -> None:
            self.speed_presses += 1

    async def go() -> None:
        app = SpeedApp()
        async with app.run_test() as pilot:
            tmap = app.query_one(TacticalMap)
            tmap.focus()
            tmap.set_zoom_keys_enabled(False)
            await pilot.press("plus")
            assert app.speed_presses == 1

    asyncio.run(go())


@pytest.mark.parametrize(
    ("kind", "progress", "payload"),
    [
        ("lance", 0.0, {"from": Vector2D(0, 0), "to": Vector2D(20, 10)}),
        ("strike", 0.2, {"from": Vector2D(0, 0), "to": Vector2D(20, 10)}),
        ("impact", 0.1, {"target_id": "p2", "position": Vector2D(40, -20), "damage": 3}),
        ("damage_text", 0.1, {"target_id": "p2", "position": Vector2D(40, -20), "text": "-3"}),
        ("explosion", 0.1, {"ship_id": "p2", "position": Vector2D(40, -20)}),
        ("salvo_launch", 0.5, {"attacker_id": "p1", "position": Vector2D(40, -20)}),
        ("incoming_fire", 0.1, {"target_id": "p1", "bearing": 90.0}),
    ],
)
def test_timeline_payload_keys_are_drawn(kind: str, progress: float, payload: dict) -> None:
    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        def frame(effects: tuple[Effect, ...]) -> Frame:
            return Frame(0.5, SHIPS, (), effects, (), {})

        tmap.show_frame(frame(()))
        bare = _text(tmap)
        tmap.show_frame(frame((Effect(kind, progress, payload),)))
        assert _text(tmap) != bare

    _run(scenario)


def test_real_turn_lance_hit_is_drawn_mid_fire() -> None:
    from dataclasses import replace as dc_replace

    from spacefleet.data.demo_data import LANCE_2
    from spacefleet.dice import DiceRoller
    from spacefleet.net.commands import Command
    from spacefleet.net.game_state import GameState
    from spacefleet.net.turn_resolver import resolve_turn
    from spacefleet.tui.model.capture import snapshot_for
    from spacefleet.tui.model.timeline import TimelineBuilder

    class AlwaysHit(DiceRoller):
        def roll_d6(self, count: int) -> list[int]:
            return [6] * count

    state = GameState.create_pve(["p1"], seed=7)
    state.dice = AlwaysHit(seed=1)
    state.ships["ai_hulk_1"].position = Vector2D(0.0, 20.0)
    state.ships["ai_hulk_2"].position = Vector2D(0.0, 500.0)
    state.ships["p1_dauntless"].weapons[2].weapon = LANCE_2
    snaps: dict[str, BattleSnapshot] = {}
    labels: dict[str, str] = {}

    def capture(phase: str, s: GameState) -> None:
        snaps[phase] = snapshot_for(s, "p1", phase, labels=labels)

    log = resolve_turn(
        state,
        {"p1_dauntless": Command("p1_dauntless", "fire", {"slot": 3, "bearing": 0.0})},
        on_phase=capture,
    )
    timeline = TimelineBuilder(snaps, log, "p1").build()
    lance = next(tr for tr in timeline.tracks if tr.kind == "lance")
    impact = next(tr for tr in timeline.tracks if tr.kind == "impact")
    assert lance.payload["hit"]

    async def scenario(app: MapApp, tmap: TacticalMap, pilot: Pilot[None]) -> None:
        # Beam alone, then impact flash / damage text on top of the beam.
        for t, drawn_kinds in ((lance.t0 + 0.01, {"lance"}), (impact.t0 + 0.01, {"impact"})):
            frame = timeline.sample(t)
            assert drawn_kinds <= {e.kind for e in frame.effects}
            tmap.show_frame(frame)
            tmap.fit_all()
            drawn = _text(tmap)
            kept = tuple(e for e in frame.effects if e.kind not in drawn_kinds | {"damage_text"})
            tmap.show_frame(dc_replace(frame, effects=kept, incoming=()))
            assert _text(tmap) != drawn, f"{drawn_kinds} at t={t} was not drawn"

    _run(scenario)
