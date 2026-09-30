"""Turn playback timeline: tracks derived from phase snapshots and a TurnLog.

``TimelineBuilder`` lays one resolved turn out on a clock in seconds at 1x:
command 0.0-0.4, fire 0.4-1.6, move 1.6-3.4, end 3.4-4.2.  Events inside a
window are staggered 0.15 s apart; a window that cannot fit its events
stretches and shifts the later ones.  ``Timeline.sample(t)`` is a pure
function of ``t`` and ``sample(duration)`` matches the ``end`` snapshot.

Movement runs at constant speed through ``after_fire -> mid_move ->
after_move`` (each half of the move window is one leg; without a
``mid_move`` snapshot there is a single leg), so a salvo impact placed at
its turn fraction (``SalvoImpactEvent.time``) meets the ship where it hit.

Fog of war: names and positions come only from the snapshots.  An event
whose origin is hidden but whose target is visible yields just the impact
plus an ``incoming_fire`` marker (bearing rounded to 45 degrees); an event
with no visible end is dropped, log line included.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from spacefleet.commander.abilities import (
    AbilityUsedEvent,
    AreaHullDamageHitEvent,
    HullRepairedEvent,
)
from spacefleet.core.types import DetectionLevel, Vector2D, heading_to_vector
from spacefleet.net.turn_resolver import (
    CriticalHitEvent,
    DestroyedEvent,
    DriftEvent,
    EndOfTurnEvent,
    FireExtinguishedEvent,
    LanceFireEvent,
    LightningStrikeEvent,
    MoraleChangeEvent,
    SalvoExpiredEvent,
    SalvoImpactEvent,
    SalvoLaunchEvent,
    SalvoMoveEvent,
    SpeedChangeEvent,
    StanceChangeEvent,
    TurnOrderEvent,
)
from spacefleet.phases.command_phase import (
    AbilityInterruptedEvent,
    AbilityPrepStartedEvent,
    AbilityRejectedEvent,
)
from spacefleet.spatial.geometry import absolute_bearing, bearing_from_to, point_to_segment_distance
from spacefleet.tui.model.snapshot import PHASES
from spacefleet.tui.model.tween import lerp, lerp_angle, lerp_vec

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.core.events import TurnEvent
    from spacefleet.models.ship import Ship
    from spacefleet.net.turn_resolver import TurnLog
    from spacefleet.tui.model.snapshot import BattleSnapshot, ProjectileView, ShipView

WINDOWS: tuple[str, ...] = ("command", "fire", "move", "end")
STAGGER = 0.15
_BASE_LEN = {"command": 0.4, "fire": 1.2, "move": 1.8, "end": 0.8}
_LEAD = {"command": 0.0, "fire": 0.1, "move": 0.0, "end": 0.05}  # first slot offset
_TAIL = {"command": 0.4, "fire": 0.5, "move": 0.0, "end": 0.6}  # room after last slot

_BEAM = 0.35
_HIT_DELAY = 0.15  # beam/strike start -> impact
_IMPACT = 0.3
_DAMAGE_TEXT = 0.8
_INCOMING = 0.8
_BURST = 0.5  # launch flash, strike line, end-of-turn pulses
_EXPLOSION = 0.6
_ABILITY = 0.4
_BAR_RAMP = 0.3
_FOLLOW = 0.15  # secondary event (destroyed, morale...) after its cause

_NON_EFFECT_KINDS = frozenset({"bar", "log"})
_STATS = ("hull", "shields", "morale")

# Snapshot to read names/positions from, per window (first present wins).
_VIEW_ORDER = {
    "command": ("after_fire", "start"),
    "fire": ("after_fire", "start"),
    "move": ("after_move", "after_fire"),
    "end": ("end", "after_move", "after_fire", "start"),
}


# Snapshot whose hull values seed the running hull tally used in log text.
_HULL_RESYNC = {"move": "after_fire", "end": "after_move"}


def _default_windows() -> dict[str, tuple[float, float]]:
    windows: dict[str, tuple[float, float]] = {}
    t = 0.0
    for name in WINDOWS:
        windows[name] = (t, round(t + _BASE_LEN[name], 6))
        t = round(t + _BASE_LEN[name], 6)
    return windows


@dataclass(frozen=True)
class Track:
    """One animated thing between ``t0`` and ``t1`` seconds (at 1x speed).

    ``kind`` values and their payload keys:

    - "ability": fleet_id, ability_id, status ("used" | "rejected" |
      "preparing" | "interrupted")
    - "lance": attacker_id, target_id (None on a miss or hidden target),
      from, to (Vector2D), hit (bool)
    - "salvo_launch": attacker_id, projectile_id (None if not matched),
      position, bearing (absolute)
    - "strike": attacker_id, target_id, from, to
    - "impact": target_id, position, damage
    - "damage_text": target_id, position, text (e.g. "-3")
    - "incoming_fire": target_id, bearing (absolute, target -> attacker,
      multiple of 45)
    - "explosion": ship_id, position
    - "shield_regen" / "fire_damage": ship_id, position, amount
    - "critical": ship_id, position, name
    - "morale": ship_id, position, old, new, source
    - "stance": ship_id, position, old, new (Stance)
    - "bar": ship_id, stat ("hull" | "shields" | "morale"), from, to
    - "log": text (``t0 == t1``)
    """

    t0: float
    t1: float
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Effect:
    """A transient visual active in a frame (beam, flash, explosion, text...).

    ``kind``/``payload`` are copied from the :class:`Track`.
    """

    kind: str
    progress: float  # 0..1 within its track
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Bars:
    hull: float
    hull_max: int
    shields: float
    shields_max: int
    morale: float
    morale_max: int


@dataclass(frozen=True)
class Frame:
    """Everything the map and panels draw at time ``t``."""

    t: float
    ships: tuple[ShipView, ...]
    projectiles: tuple[ProjectileView, ...]
    effects: tuple[Effect, ...]
    log_lines: tuple[str, ...]  # log entries whose time has passed, in order
    bars: dict[str, Bars]  # player ship id -> interpolated bars
    incoming: tuple[tuple[str, float], ...] = ()  # (target ship id, absolute bearing)
    # ship id -> polyline (move start, mid-move once passed, current position)
    # for visible ships that moved
    trails: dict[str, tuple[Vector2D, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Motion:
    """Per-object timing the builder derives for ``Timeline.sample``."""

    destroyed_at: dict[str, float] = field(default_factory=dict)
    projectile_appear: dict[str, float] = field(default_factory=dict)  # new salvos
    projectile_paths: dict[str, tuple[Vector2D, Vector2D]] = field(default_factory=dict)
    projectile_gone: dict[str, float] = field(default_factory=dict)  # impact / expiry


@dataclass(frozen=True)
class Timeline:
    snapshots: dict[str, BattleSnapshot]  # phase -> snapshot
    tracks: tuple[Track, ...]
    duration: float
    windows: dict[str, tuple[float, float]] = field(default_factory=_default_windows)
    motion: Motion = field(default_factory=Motion)

    def sample(self, t: float) -> Frame:
        t = min(max(t, 0.0), self.duration)
        end = self._snap("end")
        if t >= self.duration:
            ships, projectiles = end.ships, end.projectiles
        else:
            ships, projectiles = self._positions(t)
        effects: list[Effect] = []
        incoming: list[tuple[str, float]] = []
        log_lines: list[str] = []
        for tr in self.tracks:
            if tr.kind == "log":
                if tr.t0 <= t:
                    log_lines.append(tr.payload["text"])
            elif tr.kind not in _NON_EFFECT_KINDS and tr.t0 <= t < tr.t1:
                effects.append(Effect(tr.kind, (t - tr.t0) / (tr.t1 - tr.t0), tr.payload))
                if tr.kind == "incoming_fire":
                    incoming.append((tr.payload["target_id"], tr.payload["bearing"]))
        return Frame(
            t=t,
            ships=ships,
            projectiles=projectiles,
            effects=tuple(effects),
            log_lines=tuple(log_lines),
            bars=self._bars(t),
            incoming=tuple(incoming),
            trails=self._trails(t, ships),
        )

    # ── helpers ──────────────────────────────────────────────

    def _snap(self, phase: str) -> BattleSnapshot:
        snap = self.snapshots.get(phase)
        if snap is not None:
            return snap
        return next(iter(self.snapshots.values()))

    def _positions(self, t: float) -> tuple[tuple[ShipView, ...], tuple[ProjectileView, ...]]:
        m0, m1 = self.windows["move"]
        if t < m0:
            start, fired = self._snap("start"), self._snap("after_fire")
            known = {p.id for p in start.projectiles}
            launched = tuple(
                p
                for p in fired.projectiles
                if p.id not in known and self.motion.projectile_appear.get(p.id, m0) <= t
            )
            ships: tuple[ShipView, ...] = start.ships
            projectiles = start.projectiles + launched
        elif t < m1:
            u = (t - m0) / (m1 - m0)
            ships = self._moving_ships(u)
            projectiles = self._moving_projectiles(t, u)
        else:
            ships, projectiles = self._snap("end").ships, self._snap("end").projectiles
        return self._with_deaths(ships, t), projectiles

    def _legs(self) -> tuple[BattleSnapshot, ...]:
        """Keyframes of the move window: after_fire, [mid_move,] after_move."""
        mid = self.snapshots.get("mid_move")
        a, b = self._snap("after_fire"), self._snap("after_move")
        return (a, b) if mid is None else (a, mid, b)

    def _trails(self, t: float, ships: tuple[ShipView, ...]) -> dict[str, tuple[Vector2D, ...]]:
        m0, m1 = self.windows["move"]
        if t < m0:
            return {}
        b_by = {s.id: s for s in self._snap("after_move").ships}
        mid = self.snapshots.get("mid_move")
        mid_by = {s.id: s for s in mid.ships} if mid is not None and t >= lerp(m0, m1, 0.5) else {}
        shown = {s.id: s.position for s in ships}
        trails: dict[str, tuple[Vector2D, ...]] = {}
        for sa in self._snap("after_fire").ships:
            sb = b_by.get(sa.id)
            if sb is None:
                continue
            sm = mid_by.get(sa.id)
            points = [sa.position] if sm is None else [sa.position, sm.position]
            points.append(shown.get(sa.id, sb.position))
            if all(p.distance_to(sa.position) <= 1e-6 for p in (*points, sb.position)):
                continue
            trails[sa.id] = tuple(points)
        return trails

    def _with_deaths(self, ships: tuple[ShipView, ...], t: float) -> tuple[ShipView, ...]:
        out = []
        for s in ships:
            at = self.motion.destroyed_at.get(s.id)
            if at is not None and s.alive != (t < at):
                s = replace(s, alive=t < at)
            out.append(s)
        return tuple(out)

    def _moving_ships(self, u: float) -> tuple[ShipView, ...]:
        legs = self._legs()
        k = min(int(u * (len(legs) - 1)), len(legs) - 2)
        return _lerp_ships(legs[k], legs[k + 1], u * (len(legs) - 1) - k)

    def _moving_projectiles(self, t: float, u: float) -> tuple[ProjectileView, ...]:
        a, b = self._snap("after_fire"), self._snap("after_move")
        b_by = {p.id: p for p in b.projectiles}
        mid = lerp(*self.windows["move"], 0.5)
        out: list[ProjectileView] = []
        for pa in a.projectiles:
            pb = b_by.get(pa.id)
            if pb is None and t >= self.motion.projectile_gone.get(pa.id, mid):
                continue
            path = self.motion.projectile_paths.get(pa.id)
            if path is None:
                path = (pa.position, pb.position if pb is not None else pa.position)
            out.append(replace(pa, position=lerp_vec(path[0], path[1], u)))
        if u >= 0.5:
            a_ids = {p.id for p in a.projectiles}
            for pb in b.projectiles:
                if pb.id in a_ids:
                    continue
                path = self.motion.projectile_paths.get(pb.id)
                pos = lerp_vec(path[0], path[1], u) if path is not None else pb.position
                out.append(replace(pb, position=pos))
        return tuple(out)

    def _bars(self, t: float) -> dict[str, Bars]:
        start, end = self._snap("start"), self._snap("end")
        final = t >= self.duration
        ramps: dict[tuple[str, str], list[Track]] = {}
        for tr in self.tracks:
            if tr.kind == "bar":
                ramps.setdefault((tr.payload["ship_id"], tr.payload["stat"]), []).append(tr)
        bars: dict[str, Bars] = {}
        for view in end.ships:
            if not view.is_player or not _has_stats(view):
                continue
            first = start.ship(view.id) or view
            values: dict[str, float] = {}
            for stat in _STATS:
                value = float(getattr(view if final else first, stat) or 0)
                if not final:
                    for tr in ramps.get((view.id, stat), []):
                        if t >= tr.t1:
                            value = float(tr.payload["to"])
                        elif t > tr.t0:
                            p = (t - tr.t0) / (tr.t1 - tr.t0)
                            value = lerp(tr.payload["from"], tr.payload["to"], p)
                            break
                        else:
                            break
                values[stat] = value
            bars[view.id] = Bars(
                hull=values["hull"],
                hull_max=view.hull_max or 0,
                shields=values["shields"],
                shields_max=view.shields_max or 0,
                morale=values["morale"],
                morale_max=view.morale_max or 0,
            )
        return bars


def _has_stats(view: ShipView) -> bool:
    return all(getattr(view, stat) is not None for stat in _STATS)


def _lerp_ships(a: BattleSnapshot, b: BattleSnapshot, u: float) -> tuple[ShipView, ...]:
    """Ships of one move leg at ``u`` (0..1), at constant speed."""
    b_by = {s.id: s for s in b.ships}
    out: list[ShipView] = []
    for sa in a.ships:
        sb = b_by.get(sa.id)
        if sb is None:
            if u < 0.5:  # lost from sensors mid-move
                out.append(sa)
            continue
        base = sa if u < 0.5 else sb
        heading = base.heading
        if sa.heading is not None and sb.heading is not None:
            heading = lerp_angle(sa.heading, sb.heading, u)
        out.append(replace(base, position=lerp_vec(sa.position, sb.position, u), heading=heading))
    a_ids = {s.id for s in a.ships}
    if u >= 0.5:
        out.extend(s for s in b.ships if s.id not in a_ids)
    return tuple(out)


# ═══════════════════════════════════════════════════════════════
# Builder
# ═══════════════════════════════════════════════════════════════


@dataclass
class _Item:
    """One visible event waiting for its time slot."""

    window: str
    primary: bool  # takes a staggered slot; secondaries follow the last primary
    make: Callable[[float], list[Track]]
    touches: tuple[str, ...] = ()  # ships whose bars this event changes
    hit_delay: float = 0.0  # bars move at time + hit_delay (when the hit lands)
    frac: float | None = None  # fixed position inside the move window
    destroyed: str | None = None  # ship id exploding at this item's time
    launched: str | None = None  # projectile id appearing at this item's time
    impacted: str | None = None  # projectile id vanishing at this item's time
    time: float = 0.0


# Earliest window each event type can belong to; others inherit the cursor.
_MIN_WINDOW: tuple[tuple[tuple[type, ...], str], ...] = (
    ((LanceFireEvent, SalvoLaunchEvent, LightningStrikeEvent), "fire"),
    (
        (
            SpeedChangeEvent,
            TurnOrderEvent,
            DriftEvent,
            SalvoMoveEvent,
            SalvoImpactEvent,
            SalvoExpiredEvent,
        ),
        "move",
    ),
    ((EndOfTurnEvent, FireExtinguishedEvent), "end"),
)


def _min_window(event: TurnEvent) -> str:
    if isinstance(event, MoraleChangeEvent) and event.source in ("fire", "recovery"):
        return "end"
    for types, window in _MIN_WINDOW:
        if isinstance(event, types):
            return window
    return "command"


class TimelineBuilder:
    def __init__(
        self,
        snapshots: dict[str, BattleSnapshot],
        log: TurnLog,
        observer_player: str,
    ) -> None:
        self.snapshots = snapshots
        self.log = log
        self.observer_player = observer_player

    def build(self) -> Timeline:
        self._fire_heading: dict[str, float] = {}
        self._paths: dict[str, tuple[Vector2D, Vector2D]] = {}
        self._salvo_target: dict[str, str] = {}  # projectile id -> ship it hits this turn
        self._maneuvers: dict[str, list[SpeedChangeEvent | TurnOrderEvent]] = {}
        self._maneuver_logged: set[str] = set()
        self._last_attacker: dict[str, str] = {}  # target id -> attacker id, in log order
        expired: set[str] = set()
        for ev in self.log.events:
            if isinstance(ev, DriftEvent):
                self._fire_heading.setdefault(ev.ship.id, ev.heading_before)
            elif isinstance(ev, SalvoMoveEvent):
                first = self._paths.get(ev.proj.id)
                start = first[0] if first is not None else _copy(ev.old_pos)
                self._paths[ev.proj.id] = (start, _copy(ev.new_pos))
            elif isinstance(ev, SalvoExpiredEvent):
                expired.add(ev.proj.id)
            elif isinstance(ev, SalvoImpactEvent):
                self._salvo_target.setdefault(ev.proj.id, ev.target.id)
            elif isinstance(ev, SpeedChangeEvent | TurnOrderEvent):
                self._maneuvers.setdefault(ev.ship.id, []).append(ev)
        self._launched = self._new_projectiles_by_attacker()

        items: list[_Item] = []
        window = "command"
        self._hull = self._hulls("start")
        for ev in self.log.events:
            candidate = _min_window(ev)
            if WINDOWS.index(candidate) > WINDOWS.index(window):
                window = candidate
                if window in _HULL_RESYNC:
                    self._hull = self._hulls(_HULL_RESYNC[window])
            item = self._item(ev, window)
            if item is not None:
                items.append(item)

        windows = self._windows(items)
        self._schedule(items, windows)
        duration = windows["end"][1]

        motion = Motion(
            destroyed_at={
                it.destroyed: min(it.time, duration) for it in items if it.destroyed is not None
            },
            projectile_appear={it.launched: it.time for it in items if it.launched is not None},
            projectile_paths=dict(self._paths),
            projectile_gone=self._gone(items, windows, expired),
        )
        tracks = [tr for it in items for tr in it.make(it.time)]
        tracks.extend(self._bar_tracks(items, windows))
        clamped = [
            replace(tr, t0=min(tr.t0, duration), t1=min(max(tr.t1, tr.t0), duration))
            for tr in tracks
        ]
        clamped.sort(key=lambda tr: tr.t0)
        return Timeline(
            snapshots=dict(self.snapshots),
            tracks=tuple(clamped),
            duration=duration,
            windows=windows,
            motion=motion,
        )

    # ── scheduling ───────────────────────────────────────────

    def _windows(self, items: list[_Item]) -> dict[str, tuple[float, float]]:
        windows: dict[str, tuple[float, float]] = {}
        t = 0.0
        for name in WINDOWS:
            n = sum(1 for it in items if it.window == name and it.primary)
            length = _BASE_LEN[name]
            if n and name != "move":
                length = max(length, _LEAD[name] + (n - 1) * STAGGER + _TAIL[name])
            windows[name] = (t, round(t + length, 6))
            t = round(t + length, 6)
        return windows

    def _schedule(self, items: list[_Item], windows: dict[str, tuple[float, float]]) -> None:
        slot = dict.fromkeys(WINDOWS, 0)
        last: dict[str, float] = {}
        for it in items:
            w0, w1 = windows[it.window]
            if it.frac is not None:
                it.time = lerp(w0, w1, it.frac)
                last[it.window] = it.time
            elif it.primary:
                it.time = w0 + _LEAD[it.window] + slot[it.window] * STAGGER
                slot[it.window] += 1
                last[it.window] = it.time
            else:
                it.time = last.get(it.window, w0 + _LEAD[it.window]) + _FOLLOW

    def _gone(
        self,
        items: list[_Item],
        windows: dict[str, tuple[float, float]],
        expired: set[str],
    ) -> dict[str, float]:
        gone = dict.fromkeys(expired, windows["move"][1])
        gone.update({it.impacted: it.time for it in items if it.impacted is not None})
        return gone

    def _bar_tracks(
        self, items: list[_Item], windows: dict[str, tuple[float, float]]
    ) -> list[Track]:
        segments = (
            ("start", "after_fire", ("command", "fire")),
            ("after_fire", "after_move", ("move",)),
            ("after_move", "end", ("end",)),
        )
        seg_span = {
            0: (windows["command"][0], windows["fire"][1]),
            1: windows["move"],
            2: windows["end"],
        }
        tracks: list[Track] = []
        end = self._snap("end")
        for view in end.ships:
            if not view.is_player or not _has_stats(view):
                continue
            for stat in _STATS:
                ramps: list[tuple[float, float]] = []  # (start time, delta)
                for i, (before, after, names) in enumerate(segments):
                    v0 = self._stat(before, view.id, stat)
                    v1 = self._stat(after, view.id, stat)
                    if v0 is None or v1 is None or v0 == v1:
                        continue
                    touches = sorted(
                        {
                            it.time + it.hit_delay
                            for it in items
                            if it.window in names and view.id in it.touches
                        }
                    )
                    if not touches:
                        ramps.append((seg_span[i][0], float(v1 - v0)))
                        continue
                    ramps.extend((tt, (v1 - v0) / len(touches)) for tt in touches)
                ramps.sort(key=lambda r: r[0])
                value = float(self._stat("start", view.id, stat) or 0)
                final = float(getattr(view, stat))
                for k, (t0, delta) in enumerate(ramps):
                    t1 = t0 + _BAR_RAMP
                    if k + 1 < len(ramps):
                        t1 = min(t1, ramps[k + 1][0])
                    to = final if k == len(ramps) - 1 else value + delta
                    tracks.append(
                        Track(
                            t0,
                            max(t1, t0 + 1e-6),
                            "bar",
                            {"ship_id": view.id, "stat": stat, "from": value, "to": to},
                        )
                    )
                    value = to
        return tracks

    def _stat(self, phase: str, ship_id: str, stat: str) -> int | None:
        view = self._snap(phase).ship(ship_id)
        return None if view is None else getattr(view, stat)

    # ── lookups ──────────────────────────────────────────────

    def _snap(self, phase: str) -> BattleSnapshot:
        snap = self.snapshots.get(phase)
        if snap is not None:
            return snap
        return next(iter(self.snapshots.values()))

    def _view(
        self,
        window: str,
        ship_id: str | None,
        level: DetectionLevel = DetectionLevel.BLIP,
        order: tuple[str, ...] | None = None,
    ) -> ShipView | None:
        if ship_id is None:
            return None
        for phase in order or _VIEW_ORDER[window]:
            snap = self.snapshots.get(phase)
            view = snap.ship(ship_id) if snap is not None else None
            if view is not None:
                return view if view.detection.value >= level.value else None
        return None

    def _hulls(self, phase: str) -> dict[str, int]:
        return {s.id: s.hull for s in self._snap(phase).ships if s.hull is not None}

    def _hull_after(self, target: ShipView, damage: int) -> str:
        """`` (hull x/y)`` after ``damage`` lands, or "" when stats are hidden."""
        hull = self._hull.get(target.id)
        if hull is None or target.hull_max is None:
            return ""
        hull = max(0, hull - damage)
        self._hull[target.id] = hull
        return f" (hull {hull}/{target.hull_max})"

    def _new_projectiles_by_attacker(self) -> dict[str, list[str]]:
        known = {p.id for p in self._snap("start").projectiles}
        by_attacker: dict[str, list[str]] = {}
        for p in self._snap("after_fire").projectiles:
            if p.id not in known and p.attacker_id is not None:
                by_attacker.setdefault(p.attacker_id, []).append(p.id)
        return by_attacker

    # ── event -> item ────────────────────────────────────────

    def _item(self, ev: TurnEvent, window: str) -> _Item | None:
        if isinstance(ev, AbilityUsedEvent | AbilityRejectedEvent | AbilityPrepStartedEvent):
            return self._ability(ev, window)
        if isinstance(ev, AbilityInterruptedEvent):
            return self._ability(ev, window)
        if isinstance(ev, AreaHullDamageHitEvent):
            return self._area_damage(ev, window)
        if isinstance(ev, HullRepairedEvent):
            return self._repaired(ev, window)
        if isinstance(ev, LanceFireEvent):
            return self._lance(ev, window)
        if isinstance(ev, SalvoLaunchEvent):
            return self._launch(ev, window)
        if isinstance(ev, LightningStrikeEvent):
            return self._strike(ev, window)
        if isinstance(ev, SalvoImpactEvent):
            return self._salvo_impact(ev, window)
        if isinstance(ev, EndOfTurnEvent):
            return self._end_of_turn(ev, window)
        if isinstance(ev, DestroyedEvent):
            return self._destroyed(ev, window)
        if isinstance(ev, CriticalHitEvent):
            return self._critical(ev, window)
        if isinstance(ev, MoraleChangeEvent):
            return self._morale(ev, window)
        if isinstance(ev, StanceChangeEvent):
            return self._stance(ev, window)
        if isinstance(ev, SpeedChangeEvent | TurnOrderEvent | DriftEvent):
            return self._maneuver(ev, window)
        return None

    def _ability(
        self,
        ev: AbilityUsedEvent
        | AbilityRejectedEvent
        | AbilityPrepStartedEvent
        | AbilityInterruptedEvent,
        window: str,
    ) -> _Item | None:
        if ev.fleet_id != self.observer_player:
            return None
        if isinstance(ev, AbilityUsedEvent):
            status, text = "used", f"Ability {ev.ability_id} used"
        elif isinstance(ev, AbilityRejectedEvent):
            status, text = "rejected", f"Ability {ev.ability_id} rejected: {ev.reason}"
        elif isinstance(ev, AbilityPrepStartedEvent):
            status, text = "preparing", f"Ability {ev.ability_id} preparing ({ev.turns} turns)"
        else:
            status, text = "interrupted", f"Ability {ev.ability_id} interrupted ({ev.reason})"
        payload = {"fleet_id": ev.fleet_id, "ability_id": ev.ability_id, "status": status}

        def make(t: float) -> list[Track]:
            return [Track(t, t + _ABILITY, "ability", payload), _log(t, text)]

        return _Item(window, window == "command", make)

    def _area_damage(self, ev: AreaHullDamageHitEvent, window: str) -> _Item | None:
        target = self._view(window, ev.ship_id)
        if target is None:
            return None
        hull = self._hull_after(target, ev.hull_damage)
        text = f"{_who(target)} takes {ev.hull_damage} hull damage{hull}"

        def make(t: float) -> list[Track]:
            return [*_impact(t, target, ev.hull_damage), _log(t, text)]

        return _Item(window, True, make, touches=(ev.ship_id,))

    def _repaired(self, ev: HullRepairedEvent, window: str) -> _Item | None:
        target = self._view(window, ev.ship_id, DetectionLevel.IDENTIFIED)
        if target is None:
            return None
        text = f"{_who(target)} repaired +{ev.amount}{self._hull_after(target, -ev.amount)}"
        return _Item(window, True, lambda t: [_log(t, text)], touches=(ev.ship_id,))

    def _lance(self, ev: LanceFireEvent, window: str) -> _Item | None:
        attacker = self._view(window, ev.ship.id, DetectionLevel.CONTACT)
        result = ev.result
        target_id = result.target_ship_id if result is not None else None
        target = self._view(window, target_id)
        if attacker is None and target is None:
            return None
        if target_id is not None:
            self._last_attacker[target_id] = ev.ship.id
        damage = result.hull_damage_dealt if result is not None else 0
        heading = attacker.heading if attacker is not None else None
        if heading is None:
            heading = self._fire_heading.get(ev.ship.id, ev.ship.heading)
        bearing = absolute_bearing(heading, ev.bearing)

        if target_id is None:
            text = f"{_who(attacker)} lance misses"
        elif target is None:
            text = f"{_who(attacker)} lance hits {_who(None)}"
        else:
            hull = self._hull_after(target, damage)
            blocked = result.shield_blocked if result is not None else 0
            shields = f"{blocked} blocked by shields, " if blocked else ""
            text = (
                f"{_who(attacker)} lance hits {_who(target)}: {shields}{damage} hull damage{hull}"
            )

        def make(t: float) -> list[Track]:
            tracks = [_log(t, text)]
            if attacker is not None:
                if target is not None:
                    to = target.position
                else:
                    reach = _weapon_range(ev.ship, ev.weapon_name)
                    to = attacker.position + heading_to_vector(bearing) * reach
                payload = {
                    "attacker_id": attacker.id,
                    "target_id": target.id if target is not None else None,
                    "from": attacker.position,
                    "to": to,
                    "hit": target is not None,
                }
                tracks.append(Track(t, t + _BEAM, "lance", payload))
            if target is not None:
                hit = t + _HIT_DELAY
                tracks.extend(_impact(hit, target, damage))
                if attacker is None:
                    tracks.append(_incoming(hit, target, bearing + 180.0))
            return tracks

        touches = (target_id,) if target_id else ()
        return _Item(window, True, make, touches=touches, hit_delay=_HIT_DELAY)

    def _launch(self, ev: SalvoLaunchEvent, window: str) -> _Item | None:
        attacker = self._view(window, ev.ship.id, DetectionLevel.CONTACT)
        if attacker is None:
            return None
        queue = self._launched.get(ev.ship.id, [])
        pid = queue.pop(0) if queue else None
        proj = next((p for p in self._snap("after_fire").projectiles if p.id == pid), None)
        if proj is not None:
            bearing = proj.bearing
        else:
            bearing = absolute_bearing(attacker.heading or 0.0, ev.bearing)
        payload = {
            "attacker_id": attacker.id,
            "projectile_id": pid,
            "position": attacker.position,
            "bearing": bearing,
        }
        text = f"{_who(attacker)} fires {ev.weapon_name}"
        target_id = self._salvo_target.get(pid) if pid is not None else None
        if target_id is not None:
            text += f" at {_who(self._view(window, target_id))}"

        def make(t: float) -> list[Track]:
            return [Track(t, t + _BURST, "salvo_launch", payload), _log(t, text)]

        return _Item(window, True, make, launched=pid)

    def _strike(self, ev: LightningStrikeEvent, window: str) -> _Item | None:
        attacker = self._view(window, ev.attacker.id, DetectionLevel.CONTACT)
        target = self._view(window, ev.target.id)
        if attacker is None and target is None:
            return None
        self._last_attacker[ev.target.id] = ev.attacker.id
        crew = ev.result.total_crew_damage
        text = f"{_who(attacker)} boards {_who(target)}"
        if target is not None:
            text += f": {crew} crew damage"

        def make(t: float) -> list[Track]:
            tracks = [_log(t, text)]
            if attacker is not None and target is not None:
                payload = {
                    "attacker_id": attacker.id,
                    "target_id": target.id,
                    "from": attacker.position,
                    "to": target.position,
                }
                tracks.append(Track(t, t + _BURST, "strike", payload))
            if target is not None:
                hit = t + _HIT_DELAY
                tracks.extend(_impact(hit, target, crew))
                if attacker is None:
                    # Coarse (45 degree) bearing from live positions: strikes
                    # carry no fire-time position of the hidden boarder.
                    back = bearing_from_to(target.position, ev.attacker.position)
                    tracks.append(_incoming(hit, target, back))
            return tracks

        return _Item(window, True, make, touches=(ev.target.id,), hit_delay=_HIT_DELAY)

    def _salvo_impact(self, ev: SalvoImpactEvent, window: str) -> _Item | None:
        proj = ev.proj
        attacker = self._view(window, proj.attacker_id, DetectionLevel.CONTACT)
        target = self._view(window, ev.target.id)
        if attacker is None and target is None:
            return None
        self._last_attacker[ev.target.id] = proj.attacker_id
        r = ev.result
        damage = r.hull_damage_dealt
        frac = 0.5
        path = self._paths.get(proj.id)
        if ev.time > 0.0:
            frac = min(1.0, ev.time)
        elif path is not None and target is not None:
            frac = _fraction_along(target.position, *path)

        if target is None:
            text = f"Salvo hits {_who(None)}"
        else:
            text = (
                f"Salvo hits {_who(target)}: {r.raw_hits} hits, "
                f"{r.shield_blocked} blocked by shields, {r.armor_saves} saved by armour, "
                f"{damage} hull damage{self._hull_after(target, damage)}"
            )

        def make(t: float) -> list[Track]:
            tracks = [_log(t, text)]
            if target is not None:
                tracks.extend(_impact(t, target, damage, ev.position))
                if attacker is None:
                    tracks.append(_incoming(t, target, proj.bearing + 180.0))
            return tracks

        return _Item(window, True, make, touches=(ev.target.id,), frac=frac, impacted=proj.id)

    def _end_of_turn(self, ev: EndOfTurnEvent, window: str) -> _Item | None:
        view = self._view(window, ev.ship.id, DetectionLevel.IDENTIFIED)
        if view is None:
            return None
        parts = []
        if ev.shields_regen:
            parts.append(f"shields +{ev.shields_regen}")
        if ev.fire_damage:
            parts.append(
                f"fire {ev.fire_damage} hull damage{self._hull_after(view, ev.fire_damage)}"
            )
        text = f"{_who(view)} " + ", ".join(parts)

        def make(t: float) -> list[Track]:
            tracks = [_log(t, text)]
            for kind, amount in (
                ("shield_regen", ev.shields_regen),
                ("fire_damage", ev.fire_damage),
            ):
                if amount:
                    payload = {"ship_id": view.id, "position": view.position, "amount": amount}
                    tracks.append(Track(t, t + _BURST, kind, payload))
            if ev.fire_damage:
                tracks.append(_damage_text(t, view, f"-{ev.fire_damage}"))
            return tracks

        return _Item(window, True, make, touches=(ev.ship.id,))

    def _destroyed(self, ev: DestroyedEvent, window: str) -> _Item | None:
        order = _VIEW_ORDER[window] + tuple(reversed(PHASES))
        view = self._view(window, ev.ship.id, order=order)
        if view is None:
            return None
        text = f"{_who(view)} destroyed"
        killer_id = self._last_attacker.get(ev.ship.id)
        if killer_id is not None:
            killer = self._view(window, killer_id, DetectionLevel.CONTACT, order=order)
            text += f" by {_who(killer)}"
        payload = {"ship_id": view.id, "position": view.position}

        def make(t: float) -> list[Track]:
            return [Track(t, t + _EXPLOSION, "explosion", payload), _log(t, text)]

        return _Item(window, False, make, touches=(ev.ship.id,), destroyed=ev.ship.id)

    def _critical(self, ev: CriticalHitEvent, window: str) -> _Item | None:
        view = self._view(window, ev.ship.id, DetectionLevel.IDENTIFIED)
        if view is None:
            return None
        text = f"{_who(view)} critical: {ev.result.name}"
        payload = {"ship_id": view.id, "position": view.position, "name": ev.result.name}

        def make(t: float) -> list[Track]:
            return [Track(t, t + _BURST, "critical", payload), _log(t, text)]

        return _Item(window, False, make, touches=(ev.ship.id,))

    def _morale(self, ev: MoraleChangeEvent, window: str) -> _Item | None:
        view = self._view(window, ev.ship.id, DetectionLevel.IDENTIFIED)
        if view is None:
            return None
        source = f" ({ev.source})" if ev.source else ""
        text = f"{_who(view)} morale {ev.old_morale} → {ev.new_morale}{source}"
        payload = {
            "ship_id": view.id,
            "position": view.position,
            "old": ev.old_morale,
            "new": ev.new_morale,
            "source": ev.source,
        }

        def make(t: float) -> list[Track]:
            return [Track(t, t + _BURST, "morale", payload), _log(t, text)]

        primary = window == "end" and ev.source in ("fire", "recovery")
        return _Item(window, primary, make, touches=(ev.ship.id,))

    def _stance(self, ev: StanceChangeEvent, window: str) -> _Item | None:
        view = self._view(window, ev.ship.id, DetectionLevel.IDENTIFIED)
        if view is None:
            return None
        reason = f" ({ev.reason})" if ev.reason else ""
        text = f"{_who(view)} stance {ev.old_stance.value} → {ev.new_stance.value}{reason}"
        payload = {
            "ship_id": view.id,
            "position": view.position,
            "old": ev.old_stance,
            "new": ev.new_stance,
        }

        def make(t: float) -> list[Track]:
            return [Track(t, t + _BURST, "stance", payload), _log(t, text)]

        return _Item(window, False, make)

    def _maneuver(
        self, ev: SpeedChangeEvent | TurnOrderEvent | DriftEvent, window: str
    ) -> _Item | None:
        """One line per visible ship: speed change, turn, distance and heading.

        Emitted at the ship's first movement event; later ones are folded in.
        """
        sid = ev.ship.id
        if sid in self._maneuver_logged:
            return None
        self._maneuver_logged.add(sid)
        before = self._view(window, sid, DetectionLevel.CONTACT, order=("after_fire",))
        after = self._view(window, sid, DetectionLevel.CONTACT, order=("after_move",))
        if before is None or after is None:
            return None
        parts: list[str] = []
        turned = False
        for order in self._maneuvers.get(sid, []):
            if isinstance(order, SpeedChangeEvent) and order.old_speed != order.new_speed:
                parts.append(f"speed {order.old_speed:g} → {order.new_speed:g}")
            elif isinstance(order, TurnOrderEvent) and order.degrees:
                turned = True
                parts.append(f"turns {abs(order.degrees):g}° {order.direction}")
        mid = self._view(window, sid, DetectionLevel.CONTACT, order=("mid_move",))
        points = [before.position, after.position]
        if mid is not None:
            points.insert(1, mid.position)
        distance = sum(p.distance_to(q) for p, q in zip(points, points[1:], strict=False))
        moved = distance >= 0.05
        if moved:
            parts.append(f"moved {distance:.1f} GU")
        if after.heading is not None and (moved or turned or before.heading != after.heading):
            parts.append(f"heading {after.heading:.0f}°")
        if not parts:
            return None
        text = f"{_who(after)} " + ", ".join(parts)
        return _Item(window, True, lambda t: [_log(t, text)])


# ── track helpers ────────────────────────────────────────────


def _log(t: float, text: str) -> Track:
    return Track(t, t, "log", {"text": text})


def _damage_text(t: float, target: ShipView, text: str) -> Track:
    payload = {"target_id": target.id, "position": target.position, "text": text}
    return Track(t, t + _DAMAGE_TEXT, "damage_text", payload)


def _who(view: ShipView | None) -> str:
    """Full name and map label as the observer knows the ship."""
    if view is None or view.label == "?":
        return "unknown ship" if view is None else "unknown ship [?]"
    return f"{view.name} [{view.label}]"


def _impact(
    t: float, target: ShipView, damage: int, position: Vector2D | None = None
) -> list[Track]:
    where = target.position if position is None else position
    payload = {"target_id": target.id, "position": where, "damage": damage}
    text = f"-{damage}" if damage else "shield"  # 0 = fully absorbed by shields
    texts = {"target_id": target.id, "position": where, "text": text}
    return [
        Track(t, t + _IMPACT, "impact", payload),
        Track(t, t + _DAMAGE_TEXT, "damage_text", texts),
    ]


def _incoming(t: float, target: ShipView, bearing: float) -> Track:
    rounded = (round((bearing % 360.0) / 45.0) * 45.0) % 360.0
    return Track(t, t + _INCOMING, "incoming_fire", {"target_id": target.id, "bearing": rounded})


def _weapon_range(ship: Ship, weapon_name: str) -> float:
    return next((w.weapon.range for w in ship.weapons if w.weapon.name == weapon_name), 60.0)


def _fraction_along(point: Vector2D, start: Vector2D, end: Vector2D) -> float:
    length = start.distance_to(end)
    if length < 1e-9:
        return 0.5
    _dist, closest = point_to_segment_distance(point, start, end)
    return min(1.0, max(0.0, start.distance_to(closest) / length))


def _copy(v: Vector2D) -> Vector2D:
    return Vector2D(v.x, v.y)
