"""Braille tactical map: ships, projectiles, effects, overlays and previews.

The map only draws what it is given.  Overlay geometry (weapon arcs, sensor
radii, drift prediction) and order previews are computed by the app and
handed in; the map converts world units to dots through its ``Camera``.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget

from spacefleet.core.types import Faction, Vector2D
from spacefleet.tui.model.camera import Camera
from spacefleet.tui.model.raster import BrailleCanvas

if TYPE_CHECKING:
    from textual import events
    from textual.app import RenderResult

    from spacefleet.tui.model.snapshot import BattleSnapshot, ProjectileView, ShipView
    from spacefleet.tui.model.timeline import Effect, Frame

_SHIP_GLYPHS = "▲◥▶◢▼◣◀◤"
_ARROW_GLYPHS = "↑↗→↘↓↙←↖"

_FACTION_STYLE = {
    Faction.IMPERIAL_NAVY: ("cyan", "bold bright_cyan"),
    Faction.CHAOS_FLEET: ("red", "bold bright_red"),
}

ZOOM_STEP = 1.25
PAN_CELLS = 4
OVERLAYS = ("arcs", "sensor", "drift")
# Sensor circles: BLIP, CONTACT, IDENTIFIED thresholds.
_SENSOR_STYLES = ("dim red", "yellow", "green")

ArcSpec = tuple[float, float, float, str | None]  # start_deg, end_deg, range GU, style


def _octant(heading: float) -> int:
    return math.floor(((heading % 360.0) + 22.5) / 45.0) % 8


def heading_glyph(heading: float) -> str:
    """Ship triangle for a compass heading, by nearest octant (0 = north)."""
    return _SHIP_GLYPHS[_octant(heading)]


def arrow_glyph(bearing: float) -> str:
    """Arrow pointing along a compass bearing, by nearest octant."""
    return _ARROW_GLYPHS[_octant(bearing)]


def _unit(bearing: float) -> tuple[float, float]:
    """Dot-space unit vector for a compass bearing (screen y grows down)."""
    rad = math.radians(bearing)
    return math.sin(rad), -math.cos(rad)


def _as_vec(value: Any) -> Vector2D | None:
    if isinstance(value, Vector2D):
        return value
    if isinstance(value, tuple | list) and len(value) == 2:
        try:
            return Vector2D(float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _tremor(ship_id: str, tick: int) -> tuple[int, int]:
    """Deterministic +/-1 dot offset for a BLIP at a given tick."""
    h = zlib.crc32(f"{ship_id}:{tick}".encode())
    return h % 3 - 1, (h // 3) % 3 - 1


class TacticalMap(Widget, can_focus=True):
    """North-up braille map of the battle."""

    DEFAULT_CSS = """
    TacticalMap {
        width: 1fr;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("plus,equals_sign", "zoom_in", "Zoom +", show=False),
        Binding("minus,underscore", "zoom_out", "Zoom -", show=False),
        Binding("left,h", "pan(-1, 0)", "Pan", show=False),
        Binding("right,l", "pan(1, 0)", "Pan", show=False),
        Binding("up,k", "pan(0, -1)", "Pan", show=False),
        Binding("down,j", "pan(0, 1)", "Pan", show=False),
    ]
    # Fit / centre / overlays are app-level keys (see ``battle_app``): the
    # lowercase letters belong to the order panel.

    class ShipClicked(Message):
        def __init__(self, ship_id: str) -> None:
            super().__init__()
            self.ship_id = ship_id

    class MapClicked(Message):
        def __init__(self, world_pos: Vector2D) -> None:
            super().__init__()
            self.world_pos = world_pos

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - Textual's widget signature
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.camera = Camera(Vector2D(0.0, 0.0), 0.5, 1, 1)
        self.selected: str | None = None
        self.overlays: set[str] = set()
        self._ships: tuple[ShipView, ...] = ()
        self._projectiles: tuple[ProjectileView, ...] = ()
        self._effects: tuple[Effect, ...] = ()
        self._incoming: tuple[tuple[str, float], ...] = ()
        self._trails: dict[str, tuple[Vector2D, Vector2D]] = {}
        self._frame_t: float | None = None
        self._tick = 0
        self._fitted = False
        self._zoom_keys = True
        self._overlay_data: dict[
            str,
            tuple[
                list[ArcSpec],
                tuple[float, float, float] | None,
                tuple[float, Vector2D] | None,
            ],
        ] = {}
        self._preview: tuple[str, Any] | None = None
        self._drag_origin: tuple[int, int] | None = None
        self._dragged = False

    # -- data ---------------------------------------------------------------

    def show_snapshot(self, snapshot: BattleSnapshot) -> None:
        self._ships = snapshot.ships
        self._projectiles = snapshot.projectiles
        self._effects = ()
        self._incoming = ()
        self._trails = {}
        self._frame_t = None
        self._maybe_autofit()
        self.refresh()

    def show_frame(self, frame: Frame) -> None:
        self._ships = frame.ships
        self._projectiles = frame.projectiles
        self._effects = frame.effects
        self._incoming = frame.incoming
        self._trails = frame.trails
        self._frame_t = frame.t
        self._maybe_autofit()
        self.refresh()

    def select(self, ship_id: str | None, *, center: bool = False) -> None:
        """Select *ship_id*; the camera only moves if it is off screen (or *center*)."""
        self.selected = ship_id
        if center or not self._selected_visible():
            self.center_on_selected()
        self.refresh()

    def ship(self, ship_id: str) -> ShipView | None:
        return next((s for s in self._ships if s.id == ship_id), None)

    # -- overlays and previews ---------------------------------------------

    def set_overlay_data(
        self,
        ship_id: str,
        arcs: Sequence[ArcSpec] = (),
        sensor: tuple[float, float, float] | None = None,
        drift: tuple[float, Vector2D] | None = None,
    ) -> None:
        """Arcs use absolute compass degrees; ranges and radii are in GU."""
        self._overlay_data[ship_id] = (list(arcs), sensor, drift)
        self.refresh()

    def toggle_overlay(self, overlay: str) -> None:
        if overlay not in OVERLAYS:
            return
        self.overlays ^= {overlay}
        self.refresh()

    def set_preview(self, kind: str, data: Any) -> None:
        """``route``: path points (or {"path", "heading"}); ``aim``: (origin,
        bearing, spread_deg, range) or a dict (``OrderPanel`` keys accepted);
        ``strike``: ship ids to highlight, or {"targets": ids}."""
        self._preview = (kind, data)
        self.refresh()

    def clear_preview(self) -> None:
        self._preview = None
        self.refresh()

    # -- camera -------------------------------------------------------------

    def set_zoom_keys_enabled(self, enabled: bool) -> None:
        """Let the app reuse +/- (e.g. playback speed); the wheel still zooms."""
        self._zoom_keys = enabled

    def center_on_selected(self) -> None:
        ship = self.ship(self.selected) if self.selected else None
        if ship is not None:
            self.camera.center = ship.position
            self.refresh()

    def _selected_visible(self) -> bool:
        ship = self.ship(self.selected) if self.selected else None
        if ship is None or not (self.size.width and self.size.height):
            return True
        self._sync_size()
        col, row = self.camera.world_to_cell(ship.position)
        return 0 <= col < self.camera.cols and 0 <= row < self.camera.rows

    def fit_all(self) -> None:
        self._sync_size()
        self.camera.fit(s.position for s in self._ships)
        self._fitted = bool(self._ships)
        self.refresh()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("zoom_in", "zoom_out"):
            return self._zoom_keys
        return True

    def action_zoom_in(self) -> None:
        self.camera.zoom(ZOOM_STEP)
        self.refresh()

    def action_zoom_out(self) -> None:
        self.camera.zoom(1 / ZOOM_STEP)
        self.refresh()

    def action_pan(self, dx: int, dy: int) -> None:
        self.camera.pan(dx * PAN_CELLS, dy * PAN_CELLS)
        self.refresh()

    def _sync_size(self) -> None:
        self.camera.cols = max(1, self.size.width)
        self.camera.rows = max(1, self.size.height)

    def _maybe_autofit(self) -> None:
        if not self._fitted and self._ships and self.size.width and self.size.height:
            self.fit_all()

    def on_mount(self) -> None:
        self.set_interval(0.25, self._advance_tremor)

    def on_resize(self, event: events.Resize) -> None:
        self._sync_size()
        self._maybe_autofit()
        self.refresh()

    def _advance_tremor(self) -> None:
        self._tick += 1
        if self._frame_t is None and any(s.alive and s.heading is None for s in self._ships):
            self.refresh()

    # -- mouse ----------------------------------------------------------------

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._wheel_zoom(event, ZOOM_STEP)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self._wheel_zoom(event, 1 / ZOOM_STEP)

    def _wheel_zoom(self, event: events.MouseEvent, factor: float) -> None:
        event.stop()
        anchor = self._cell_to_world(event.x, event.y)
        self.camera.zoom(factor, anchor)
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        self._drag_origin = (event.x, event.y)
        self._dragged = False
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_origin is None or not event.button:
            return
        ox, oy = self._drag_origin
        dx, dy = event.x - ox, event.y - oy
        if dx or dy:
            self.camera.pan(-dx, -dy)
            self._drag_origin = (event.x, event.y)
            self._dragged = True
            self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_origin is None:
            return
        self._drag_origin = None
        self.release_mouse()
        if self._dragged:
            return
        ship_id = self.ship_at(event.x, event.y)
        if ship_id is not None:
            self.post_message(self.ShipClicked(ship_id))
        else:
            self.post_message(self.MapClicked(self._cell_to_world(event.x, event.y)))

    def ship_at(self, col: int, row: int) -> str | None:
        """Nearest visible ship whose glyph is within one cell of ``(col, row)``."""
        best: tuple[int, str] | None = None
        for ship in self._ships:
            sc, sr = self.camera.world_to_cell(ship.position)
            if abs(sc - col) <= 1 and abs(sr - row) <= 1:
                dist = abs(sc - col) + abs(sr - row)
                if best is None or dist < best[0]:
                    best = (dist, ship.id)
        return best[1] if best else None

    def _cell_to_world(self, col: int, row: int) -> Vector2D:
        return self.camera.dot_to_world(col * 2 + 1, row * 4 + 2)

    # -- rendering ----------------------------------------------------------

    def render(self) -> RenderResult:
        return Text("\n").join(self.render_lines_text())

    def render_lines_text(self) -> list[Text]:
        self._sync_size()
        canvas = BrailleCanvas(self.camera.cols, self.camera.rows)
        self._draw_overlays(canvas)
        self._draw_preview(canvas)
        self._draw_effect_geometry(canvas)
        self._draw_projectiles(canvas)
        self._draw_trails(canvas)
        self._draw_ships(canvas)
        self._draw_incoming(canvas)
        self._draw_effect_text(canvas)
        self._draw_scale_bar(canvas)
        return canvas.render()

    def _dot(self, p: Vector2D) -> tuple[float, float]:
        return self.camera.world_to_dot(p)

    def _cell_of_dot(self, dx: float, dy: float) -> tuple[int, int]:
        return math.floor(dx) // 2, math.floor(dy) // 4

    def _ship_cell(self, ship: ShipView) -> tuple[int, int]:
        dx, dy = self._dot(ship.position)
        if ship.heading is None and ship.alive:
            tick = int(self._frame_t * 8) if self._frame_t is not None else self._tick
            ox, oy = _tremor(ship.id, tick)
            dx, dy = dx + ox, dy + oy
        return self._cell_of_dot(dx, dy)

    def _draw_ships(self, canvas: BrailleCanvas) -> None:
        strike = self._strike_targets()
        for ship in self._ships:
            col, row = self._ship_cell(ship)
            normal, bright = _FACTION_STYLE.get(ship.faction, ("white", "bold white"))
            style = bright if ship.is_player else normal
            if not ship.alive:
                glyph, style = "✕", "dim"
            elif ship.heading is None:
                glyph = "?"
            else:
                glyph = heading_glyph(ship.heading)
            if ship.id in strike:
                style = f"{style} underline magenta"
            if ship.id == self.selected:
                style = f"{style} reverse bold"
            canvas.put_text(col, row, glyph, style)
            if ship.label and ship.label != "?":
                canvas.put_text(col + 1, row, ship.label, "dim" if not ship.alive else normal)

    def _draw_trails(self, canvas: BrailleCanvas) -> None:
        """Dim line from each moving ship's start to where it is now."""
        for ship_id, (start, now) in self._trails.items():
            ship = self.ship(ship_id)
            if ship is None:
                continue
            normal, _bright = _FACTION_STYLE.get(ship.faction, ("white", "bold white"))
            canvas.line(*self._dot(start), *self._dot(now), f"dim {normal}")

    def _draw_projectiles(self, canvas: BrailleCanvas) -> None:
        for proj in self._projectiles:
            dx, dy = self._dot(proj.position)
            ux, uy = _unit(proj.bearing)
            for step in (3, 5, 7):
                canvas.set_dot(dx - ux * step, dy - uy * step, "yellow")
            col, row = self._cell_of_dot(dx, dy)
            canvas.put_text(col, row, "•", "bold yellow")

    def _draw_incoming(self, canvas: BrailleCanvas) -> None:
        incoming = dict.fromkeys(self._incoming)
        for eff in self._effects:
            if eff.kind == "incoming_fire":
                target = eff.payload.get("target_id")
                bearing = _as_float(eff.payload.get("bearing"))
                if isinstance(target, str) and bearing is not None:
                    incoming[(target, bearing)] = None
        for target_id, bearing in incoming:
            ship = self.ship(target_id)
            if ship is None:
                continue
            col, row = self._ship_cell(ship)
            ux, uy = _unit(bearing)
            canvas.put_text(
                col + round(ux), row + round(uy), arrow_glyph(bearing + 180.0), "bold red"
            )

    def _draw_effect_geometry(self, canvas: BrailleCanvas) -> None:
        for eff in self._effects:
            p = eff.payload
            progress = min(1.0, max(0.0, eff.progress))
            if eff.kind in ("lance", "strike"):
                a, b = _as_vec(p.get("from")), _as_vec(p.get("to"))
                if a is None or b is None:
                    continue
                if eff.kind == "lance" and int(progress * 6) % 2:
                    continue  # blink
                style = "bold bright_white" if eff.kind == "lance" else "magenta"
                canvas.line(*self._dot(a), *self._dot(b), style, dashed=eff.kind == "strike")
            elif eff.kind == "explosion":
                at = _as_vec(p.get("position"))
                if at is not None:
                    cx, cy = self._dot(at)
                    style = "bold bright_yellow" if progress < 0.5 else "red"
                    canvas.circle(cx, cy, 1.0 + progress * 6.0, style)
            elif eff.kind == "salvo_launch":
                at = _as_vec(p.get("position"))
                if at is not None:
                    cx, cy = self._dot(at)
                    r = 1.0 + progress * 2.0
                    for deg in range(0, 360, 45):
                        ux, uy = _unit(deg)
                        canvas.set_dot(cx + ux * r, cy + uy * r, "yellow")

    def _draw_effect_text(self, canvas: BrailleCanvas) -> None:
        for eff in self._effects:
            p = eff.payload
            progress = min(1.0, max(0.0, eff.progress))
            at = _as_vec(p.get("position"))
            if at is None:
                continue
            col, row = self._cell_of_dot(*self._dot(at))
            if eff.kind == "impact" and progress < 0.7:
                canvas.put_text(col, row, "✶" if int(progress * 6) % 2 == 0 else "*", "bold red")
            elif eff.kind == "damage_text":
                text = str(p.get("text", ""))
                if text:
                    canvas.put_text(col + 1, row - 1 - int(progress * 3), text, "bold red")
            elif eff.kind == "explosion" and progress < 0.3:
                canvas.put_text(col, row, "✺", "bold bright_yellow")

    # -- overlays / previews ----------------------------------------------

    def _draw_overlays(self, canvas: BrailleCanvas) -> None:
        if not self.overlays or self.selected is None:
            return
        ship = self.ship(self.selected)
        data = self._overlay_data.get(self.selected)
        if ship is None or data is None:
            return
        arcs, sensor, drift = data
        cx, cy = self._dot(ship.position)
        gu = self.camera.gu_per_dot
        if "arcs" in self.overlays:
            for start, end, rng, style in arcs:
                canvas.sector(cx, cy, rng / gu, start, end, style or "yellow")
        if "sensor" in self.overlays and sensor is not None:
            for radius, style in zip(sensor, _SENSOR_STYLES, strict=True):
                canvas.circle(cx, cy, radius / gu, style)
        if "drift" in self.overlays and drift is not None:
            heading, predicted = drift
            ux, uy = _unit(heading)
            canvas.line(cx, cy, cx + ux * 8, cy + uy * 8, "bright_white")
            px, py = self._dot(predicted)
            canvas.line(cx, cy, px, py, "dim", dashed=True)
            col, row = self._cell_of_dot(px, py)
            canvas.put_text(col, row, heading_glyph(heading), "dim")

    def _strike_targets(self) -> set[str]:
        if self._preview is None or self._preview[0] != "strike":
            return set()
        data = self._preview[1]
        if isinstance(data, dict):
            data = data.get("targets", ())
        if isinstance(data, str | bytes) or not isinstance(data, Iterable):
            return set()
        return {s for s in data if isinstance(s, str)}

    def _draw_preview(self, canvas: BrailleCanvas) -> None:
        if self._preview is None:
            return
        kind, data = self._preview
        if kind == "route":
            self._draw_route(canvas, data)
        elif kind == "aim":
            self._draw_aim(canvas, data)
        elif kind == "strike":
            for ship_id in self._strike_targets():
                ship = self.ship(ship_id)
                if ship is not None:
                    canvas.circle(*self._dot(ship.position), 4.0, "magenta")

    def _draw_route(self, canvas: BrailleCanvas, data: Any) -> None:
        heading: float | None = None
        if isinstance(data, dict):
            heading = _as_float(data.get("heading"))
            data = data.get("path", ())
        if not isinstance(data, Iterable):
            return
        pts = [v for v in (_as_vec(d) for d in data) if v is not None]
        if not pts:
            return
        for a, b in zip(pts, pts[1:], strict=False):
            canvas.line(*self._dot(a), *self._dot(b), "bright_white", dashed=True)
        if heading is None and len(pts) >= 2:
            d = pts[-1] - pts[-2]
            heading = math.degrees(math.atan2(d.x, d.y)) % 360.0
        col, row = self._cell_of_dot(*self._dot(pts[-1]))
        canvas.put_text(col, row, heading_glyph(heading) if heading is not None else "◇", "dim")

    def _draw_aim(self, canvas: BrailleCanvas, data: Any) -> None:
        if isinstance(data, dict):
            # OrderPanel.PreviewChanged sends bearing_abs / spread_deg.
            fields = [
                data.get("origin"),
                data.get("bearing_abs", data.get("bearing")),
                data.get("spread_deg", data.get("spread")),
                data.get("range"),
            ]
        elif isinstance(data, tuple | list) and len(data) == 4:
            fields = list(data)
        else:
            return
        origin = _as_vec(fields[0])
        bearing, spread, rng = (_as_float(f) for f in fields[1:])
        if origin is None or bearing is None or spread is None or rng is None:
            return
        ox, oy = self._dot(origin)
        r = rng / self.camera.gu_per_dot
        ux, uy = _unit(bearing)
        canvas.line(ox, oy, ox + ux * r, oy + uy * r, "bold bright_red")
        for edge in (bearing - spread, bearing + spread):
            ex, ey = _unit(edge)
            canvas.line(ox, oy, ox + ex * r, oy + ey * r, "red", dashed=True)

    def _draw_scale_bar(self, canvas: BrailleCanvas) -> None:
        max_cells = max(2, min(12, canvas.cols // 4))
        cells, gu = self.camera.scale_bar(max_cells)
        bar = "├" + "─" * max(0, cells - 2) + "┤" if cells >= 2 else "│"
        canvas.put_text(0, canvas.rows - 1, f"{bar} {gu:g} GU", "dim")
