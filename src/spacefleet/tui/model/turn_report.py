"""End-of-turn report: what each visible ship dealt, took and lost.

Built from the phase snapshots (already fog-of-war filtered) and the turn
log.  A ship counts as visible when any snapshot shows it at CONTACT or
better; damage dealt by anything else is pooled under one ``unknown ship``
row, and damage taken by hidden ships is left out entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.core.types import DetectionLevel
from spacefleet.net.turn_resolver import DestroyedEvent, LanceFireEvent, SalvoImpactEvent
from spacefleet.tui.model.snapshot import PHASES

if TYPE_CHECKING:
    from spacefleet.combat.resolution import AttackResult
    from spacefleet.net.turn_resolver import TurnLog
    from spacefleet.tui.model.snapshot import BattleSnapshot, ShipView

UNKNOWN_SHIP = "unknown ship"


@dataclass(frozen=True)
class ShipReport:
    ship_id: str | None  # None for the pooled unknown-ship row
    label: str
    name: str
    is_player: bool
    damage_dealt: int = 0  # hull damage inflicted on visible ships
    shield_dealt: int = 0  # hits the targets' shields stopped
    shield_taken: int = 0  # hits stopped by shields
    hull_taken: int = 0
    morale_before: int | None = None
    morale_after: int | None = None
    destroyed: bool = False

    @property
    def display_name(self) -> str:
        return self.name if self.ship_id is None else f"{self.name} [{self.label}]"

    @property
    def morale_change(self) -> int | None:
        if self.morale_before is None or self.morale_after is None:
            return None
        return self.morale_after - self.morale_before


@dataclass(frozen=True)
class TurnReport:
    turn: int
    ships: tuple[ShipReport, ...]  # own ships, then contacts, then unknown
    destroyed: tuple[str, ...]  # display names, in the order they died


def build_turn_report(
    snapshots: dict[str, BattleSnapshot], log: TurnLog, observer_player: str
) -> TurnReport:
    """Summarise one resolved turn as *observer_player* saw it.

    *observer_player* is implied by *snapshots* (they were captured for that
    player); it is accepted so callers state whose view they want.
    """
    del observer_player
    phases = [p for p in PHASES if p in snapshots] or sorted(snapshots)
    views = _visible_views(snapshots, phases)
    dealt: dict[str | None, int] = {}
    dealt_shields: dict[str | None, int] = {}
    shields: dict[str, int] = {}
    hull: dict[str, int] = {}
    killed: list[str] = []

    def hit(attacker_id: str | None, result: AttackResult | None) -> None:
        if result is None or result.target_ship_id not in views:
            return
        target = result.target_ship_id
        attacker = attacker_id if attacker_id in views else None
        dealt[attacker] = dealt.get(attacker, 0) + result.hull_damage_dealt
        dealt_shields[attacker] = dealt_shields.get(attacker, 0) + result.shield_blocked
        shields[target] = shields.get(target, 0) + result.shield_blocked
        hull[target] = hull.get(target, 0) + result.hull_damage_dealt

    for ev in log.events:
        if isinstance(ev, SalvoImpactEvent):
            hit(ev.proj.attacker_id, ev.result)
        elif isinstance(ev, LanceFireEvent):
            hit(ev.ship.id, ev.result)
        elif isinstance(ev, DestroyedEvent) and ev.ship.id in views:
            killed.append(ev.ship.id)
    for ship_id in views:  # deaths the log did not announce
        start, end = _stat_views(snapshots, phases, ship_id)
        if start is not None and start.alive and end is not None and not end.alive:
            killed.append(ship_id)
    killed = list(dict.fromkeys(killed))

    rows: list[ShipReport] = []
    for ship_id, view in views.items():
        start, end = _stat_views(snapshots, phases, ship_id)
        rows.append(
            ShipReport(
                ship_id=ship_id,
                label=view.label,
                name=view.name,
                is_player=view.is_player,
                damage_dealt=dealt.get(ship_id, 0),
                shield_dealt=dealt_shields.get(ship_id, 0),
                shield_taken=shields.get(ship_id, 0),
                hull_taken=hull.get(ship_id, 0),
                morale_before=start.morale if start is not None else None,
                morale_after=end.morale if end is not None else None,
                destroyed=ship_id in killed,
            )
        )
    rows.sort(key=lambda r: not r.is_player)
    if dealt.get(None) or dealt_shields.get(None):
        rows.append(
            ShipReport(
                ship_id=None,
                label="?",
                name=UNKNOWN_SHIP,
                is_player=False,
                damage_dealt=dealt.get(None, 0),
                shield_dealt=dealt_shields.get(None, 0),
            )
        )
    turn = snapshots[phases[-1]].turn if phases else log.turn
    destroyed = tuple(views[s].name + f" [{views[s].label}]" for s in killed)
    return TurnReport(turn=turn, ships=tuple(rows), destroyed=destroyed)


def format_turn_report(report: TurnReport) -> list[str]:
    """Plain-text lines: title, destroyed ships, then one row per ship."""
    lines = [f"Turn {report.turn} report"]
    if report.destroyed:
        lines.append("Destroyed: " + ", ".join(report.destroyed))
    if not report.ships:
        lines.append("No ships in sight.")
        return lines
    width = max(len("Ship"), *(len(r.display_name) for r in report.ships))
    lines.append("")
    lines.append(f"{'Ship':<{width}}  Dealt (shield / hull)  Taken (shield / hull)  Morale")
    for r in report.ships:
        dealt = f"{r.shield_dealt} / {r.damage_dealt}"
        taken = f"{r.shield_taken} / {r.hull_taken}"
        change = r.morale_change
        morale = "-" if change is None else f"{change:+d}"
        if r.destroyed:
            morale += "  DESTROYED"
        lines.append(f"{r.display_name:<{width}}  {dealt:>21}  {taken:>21}  {morale}")
    return lines


def _visible_views(snapshots: dict[str, BattleSnapshot], phases: list[str]) -> dict[str, ShipView]:
    """Latest CONTACT-or-better view of every ship, in first-seen order."""
    order: list[str] = []
    latest: dict[str, ShipView] = {}
    for phase in phases:
        for view in snapshots[phase].ships:
            if view.detection.value < DetectionLevel.CONTACT.value:
                continue
            if view.id not in latest:
                order.append(view.id)
            latest[view.id] = view
    return {ship_id: latest[ship_id] for ship_id in order}


def _stat_views(
    snapshots: dict[str, BattleSnapshot], phases: list[str], ship_id: str
) -> tuple[ShipView | None, ShipView | None]:
    """First and last snapshot views of *ship_id*, whatever their level."""
    seen = [v for p in phases if (v := snapshots[p].ship(ship_id)) is not None]
    return (seen[0], seen[-1]) if seen else (None, None)
