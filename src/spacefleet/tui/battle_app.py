"""Full-screen Textual battle: plan orders, resolve the turn, watch it play back.

States: PLANNING -> (confirm summary) -> RESOLVING -> PLAYBACK -> (turn
report) -> PLANNING.  Before every PLANNING the battle ends, in this order,
on defeat, victory or the turn limit; an ending battle skips the report.
The report shows only after a turn's first playback, not after a replay.

Key map
-------

======================  =====================================================
Key                     Action
======================  =====================================================
Tab / Shift+Tab         Next / previous own ship (planning)
Arrows                  Order panel top menu: ↑/↓ speed, ←/→ turn (maneuver)
f b t h p               Order panel: Fire, Boarding, Tactic, Ability, Pass
Esc                     Order panel: back one menu level
Enter                   Confirm turn (order panel at its top menu)
r                       Replay the last resolved turn
L                       Battle log, last turn's report on top (planning)
Space                   Skip playback to the end
+ / -                   Zoom (planning) · playback speed 0.5x/1x/2x
Mouse wheel / drag      Zoom / pan the map
Arrows (h j k l)        Pan the map while it has focus (arrows: submenu cursor
                        while the order panel is inside a submenu)
F / C                   Fit every ship / centre on the selected ship
A / S / D               Overlays: weapon arcs, sensor rings, drift
o                       Show / hide the side panel (terminals < 120 columns)
?                       Show this key map (Esc, ? or q closes it)
q / Ctrl+C              Leave the battle (asks: abandon, surrender, cancel)
======================  =====================================================

Lowercase letters belong to the order panel; the map only owns zoom and pan,
so map commands are uppercase app-level keys that work regardless of focus.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar, cast

from textual.app import App
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Static

from spacefleet.campaign.models import BattleOutcome
from spacefleet.core.types import Arc
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.data.stance_registry import StanceRegistry
from spacefleet.net.ai_controller import AIController
from spacefleet.net.turn_resolver import resolve_turn
from spacefleet.spatial.detection import effective_sensor_range
from spacefleet.tui.model.capture import snapshot_for
from spacefleet.tui.model.orders import (
    OrderDraft,
    alive_player_ids,
    finalize,
    hostile_contacts,
    predict_move,
)
from spacefleet.tui.model.snapshot import PHASES
from spacefleet.tui.model.timeline import TimelineBuilder
from spacefleet.tui.model.turn_report import build_turn_report
from spacefleet.tui.widgets.event_log import EventLog, turn_separator
from spacefleet.tui.widgets.log_screen import LogScreen
from spacefleet.tui.widgets.order_panel import (
    AbilitySet,
    ManeuverSet,
    OrderPanel,
    OrderSet,
    PreviewChanged,
    PreviewCleared,
    StanceSet,
)
from spacefleet.tui.widgets.status_panel import ShipSelected, StatusPanel
from spacefleet.tui.widgets.tactical_map import ArcSpec, TacticalMap
from spacefleet.tui.widgets.turn_report_screen import TurnReportScreen

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.geometry import Size
    from textual.timer import Timer

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.cli.terminal_ui import TerminalUI
    from spacefleet.core.types import Vector2D
    from spacefleet.models.ship import Ship
    from spacefleet.net.commands import Command, Maneuver
    from spacefleet.net.game_state import GameState
    from spacefleet.tui.model.snapshot import BattleSnapshot
    from spacefleet.tui.model.timeline import Timeline
    from spacefleet.tui.model.turn_report import TurnReport

TURN_LIMIT = 60
MIN_SIZE = (80, 24)
WIDE_COLUMNS = 120
FPS = 30
SPEEDS = (0.5, 1.0, 2.0)

PLANNING, RESOLVING, PLAYBACK = "PLANNING", "RESOLVING", "PLAYBACK"

# Prow-relative (start, end) of each firing arc, swept clockwise.
_ARC_SPANS = {
    Arc.PROW: (-45.0, 45.0),
    Arc.STARBOARD: (45.0, 135.0),
    Arc.AFT: (135.0, 225.0),
    Arc.PORT: (225.0, 315.0),
    Arc.DORSAL: (-135.0, 135.0),
}
_ARC_STYLES = {
    Arc.PROW: "yellow",
    Arc.STARBOARD: "green",
    Arc.AFT: "magenta",
    Arc.PORT: "red",
    Arc.DORSAL: "blue",
}


# ── pending-turn summary ────────────────────────────────────────────


def format_pending(
    session: BattleSession, draft: OrderDraft, *, labels: dict[str, str] | None = None
) -> str:
    """Human-readable orders for every alive player ship; idle ships pass.

    Each line is ``Name: <maneuver>; <action>``.  *labels* (ship id -> map
    label) names targets as on the map.
    """
    state = session.state
    lines = ["Pending turn:"]
    for ship_id in alive_player_ids(session):
        ship = state.ships[ship_id]
        command = draft.commands.get(ship_id)
        action = (
            "pass (no order)" if command is None else format_command(session, ship, command, labels)
        )
        text = f"{format_maneuver(ship, draft.maneuvers.get(ship_id))}; {action}"
        stance = draft.stances.get(ship_id)
        if stance is not None:
            text += f"; stance {stance.value.replace('_', ' ').title()}"
        lines.append(f"  {ship.name}: {text}")
    if draft.ability is None:
        lines.append("  Commander ability: None")
    else:
        definition = SkillRegistry.get_active(draft.ability.ability_id)
        name = definition.name if definition else draft.ability.ability_id
        suffix = ""
        if draft.ability.target_ship_id is not None:
            suffix = f" → {_target_name(session, draft.ability.target_ship_id)}"
        elif draft.ability.target_position is not None:
            suffix = f" at {draft.ability.target_position}"
        lines.append(f"  Commander ability: {name}{suffix}")
    return "\n".join(lines)


def format_maneuver(ship: Ship, maneuver: Maneuver | None) -> str:
    """``speed 8, turn 30° starboard``; ``hold course`` when nothing changes."""
    parts = []
    if maneuver is not None and maneuver.speed is not None and maneuver.speed != ship.speed:
        parts.append(f"speed {maneuver.speed:g}")
    if maneuver is not None and maneuver.turn:
        side = "port" if maneuver.turn < 0 else "starboard"
        parts.append(f"turn {abs(maneuver.turn):g}° {side}")
    return ", ".join(parts) or "hold course"


def format_command(
    session: BattleSession,
    ship: Ship,
    command: Command,
    labels: dict[str, str] | None = None,
) -> str:
    """The action part of *command*: ``fire 2 weapons at E1``, ``pass``, ..."""
    args = command.args
    if command.action == "pass":
        return "pass"
    if command.action == "strike":
        target = _target_label(session, str(args["target"]), labels)
        return f"board {target}, target {args['subsystem']}"
    shots = cast("list[dict[str, int | float | str]]", args.get("shots", [args]))
    # Weapons sharing an aim are counted; a lone weapon is named.
    groups: dict[str, list[str]] = {}
    for shot in shots:
        mount = next(m for m in ship.weapons if m.slot_id == int(shot["slot"]))
        target_id = shot.get("target")
        aim = (
            f"bearing {float(shot['bearing']):g}° rel"
            if target_id is None
            else _target_label(session, str(target_id), labels)
        )
        groups.setdefault(aim, []).append(mount.display_name)
    parts = [
        f"{names[0] if len(names) == 1 else f'{len(names)} weapons'} at {aim}"
        for aim, names in groups.items()
    ]
    return "fire " + ", ".join(parts)


def _target_label(session: BattleSession, target_id: str, labels: dict[str, str] | None) -> str:
    """The target's map label when known, else its name as seen."""
    if labels and target_id in labels:
        return labels[target_id]
    return _target_name(session, target_id)


def _target_name(session: BattleSession, target_id: str) -> str:
    state = session.state
    if target_id in state.player_ships[session.player_id]:
        return state.ships[target_id].name
    for ship_id in alive_player_ids(session):
        for contact in hostile_contacts(session, state.ships[ship_id]):
            if contact.ship.id == target_id:
                return contact.display_name
    return "Contact"


# ── modal screens ───────────────────────────────────────────────────


class ConfirmTurnScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmTurnScreen { align: center middle; }
    ConfirmTurnScreen > Vertical {
        width: 72; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    ConfirmTurnScreen #summary { height: auto; margin-bottom: 1; }
    ConfirmTurnScreen Horizontal { height: auto; }
    ConfirmTurnScreen Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "choose(True)", "Resolve"),
        Binding("escape,n", "choose(False)", "Revise"),
    ]

    def __init__(self, summary: str) -> None:
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Confirm turn", classes="title")
            yield Static(self.summary, id="summary", markup=False)
            with Horizontal():
                yield Button("Resolve [Enter]", id="resolve", variant="primary")
                yield Button("Revise [Esc]", id="revise")

    def on_mount(self) -> None:
        self.query_one("#resolve", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "resolve")

    def action_choose(self, resolve: bool) -> None:
        self.dismiss(resolve)


class QuitScreen(ModalScreen[BattleOutcome | None]):
    DEFAULT_CSS = """
    QuitScreen { align: center middle; }
    QuitScreen > Vertical {
        width: 64; height: auto; border: thick $error; background: $surface; padding: 1 2;
    }
    QuitScreen Horizontal { height: auto; margin-top: 1; }
    QuitScreen Button { margin-right: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "choose('abandon')", "Abandon"),
        Binding("s", "choose('surrender')", "Surrender"),
        Binding("escape,n", "choose('cancel')", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "Leave this battle?\nAbandon returns to the previous campaign interval; "
                "surrender ends the battle as a loss."
            )
            with Horizontal():
                yield Button("Abandon [y]", id="abandon", variant="error")
                yield Button("Surrender [s]", id="surrender", variant="warning")
                yield Button("Cancel [Esc]", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(str(event.button.id))

    def action_choose(self, choice: str) -> None:
        outcomes = {"abandon": BattleOutcome.ABANDONED, "surrender": BattleOutcome.SURRENDER}
        self.dismiss(outcomes.get(choice))


def _key_map() -> str:
    """The key table from this module's docstring, without its rules."""
    rows = (__doc__ or "").split("Key map", 1)[-1].splitlines()
    rules = [i for i, row in enumerate(rows) if row.startswith("====")]
    return "\n".join(rows[rules[0] + 1 : rules[-1]]) if len(rules) >= 2 else ""


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Vertical {
        width: 84; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    HelpScreen #keys { height: auto; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,question_mark,q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Keys", classes="title")
            yield Static(_key_map(), id="keys", markup=False)


# ── app ─────────────────────────────────────────────────────────────


class BattleApp(App[BattleOutcome]):
    CSS = """
    #header { height: 1; background: $primary-background; padding: 0 1; }
    #body { height: 1fr; layers: base overlay; }
    #map { layer: base; }
    #side { width: 44; height: 1fr; border-left: solid $primary; layer: base; }
    #side.-narrow { dock: right; layer: overlay; display: none; background: $surface; }
    #side.-narrow.-open { display: block; }
    #log { height: 6; border-top: solid $primary; }
    #too-small { display: none; height: 1fr; content-align: center middle; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("question_mark", "help", "Help"),
        Binding("enter", "confirm_turn", "Confirm", priority=True),
        Binding("tab", "cycle_ship(1)", "Ship", priority=True),
        Binding("shift+tab", "cycle_ship(-1)", "Ship", show=False, priority=True),
        # Order letters reach the panel even while the map has focus (where
        # h pans instead); the panel's own bindings win when it is focused.
        Binding("f", "order('fire')", "Fire", show=False),
        Binding("b", "order('strike')", "Board", show=False),
        Binding("t", "order('tactic')", "Tactic", show=False),
        Binding("h", "order('ability')", "Ability", show=False),
        Binding("p", "order('pass')", "Pass", show=False),
        Binding("escape", "order('back')", "Back", show=False),
        Binding("space", "skip", "Skip"),
        Binding("r", "replay", "Replay"),
        Binding("L", "log", "Log"),
        Binding("plus,equals_sign", "faster", "Speed/zoom", show=False),
        Binding("minus,underscore", "slower", "Speed/zoom", show=False),
        Binding("F", "fit", "Fit", show=False),
        Binding("C", "center", "Centre", show=False),
        Binding("A", "overlay('arcs')", "Arcs", show=False),
        Binding("S", "overlay('sensor')", "Sensor", show=False),
        Binding("D", "overlay('drift')", "Drift", show=False),
        Binding("o", "toggle_side", "Panel"),
        Binding("q", "request_quit", "Quit"),
        Binding("ctrl+c,ctrl+q", "request_quit", "Quit", show=False, priority=True),
    ]

    def __init__(
        self,
        session: BattleSession,
        *,
        turn_limit: int = TURN_LIMIT,
        ai: AIController | None = None,
    ) -> None:
        if turn_limit < 1:
            raise ValueError("turn limit must be positive")
        super().__init__()
        self.session = session
        self.turn_limit = turn_limit
        self.ai = ai or AIController()
        self.draft = OrderDraft()
        self.phase = PLANNING
        self.selected: str | None = None
        self.speed = 1.0
        self.timeline: Timeline | None = None
        self.playhead = 0.0
        self._replaying = False
        self._timer: Timer | None = None
        self._last_tick = 0.0
        self._labels: dict[str, str] = {}
        self._snapshot: BattleSnapshot | None = None
        self._log_base: list[str] = []
        self._log_shown = 0
        self._too_small = False
        # Each resolved turn's full log, oldest first, and its report.
        self.history: list[tuple[int, list[str]]] = []
        self.last_report: TurnReport | None = None

    # ── layout ──────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static(id="header", markup=False)
        with Horizontal(id="body"):
            yield TacticalMap(id="map")
            with VerticalScroll(id="side"):
                yield StatusPanel(id="status")
                yield OrderPanel(self.session, self.draft, id="orders")
        yield EventLog(id="log")
        yield Static(
            f"Terminal too small: resize to at least {MIN_SIZE[0]}×{MIN_SIZE[1]}.",
            id="too-small",
            markup=False,
        )
        yield Footer()

    @property
    def tactical_map(self) -> TacticalMap:
        return self.query_one("#map", TacticalMap)

    @property
    def order_panel(self) -> OrderPanel:
        return self.query_one("#orders", OrderPanel)

    @property
    def status_panel(self) -> StatusPanel:
        return self.query_one("#status", StatusPanel)

    @property
    def event_log(self) -> EventLog:
        return self.query_one("#log", EventLog)

    @property
    def too_small(self) -> bool:
        return self._too_small

    def on_mount(self) -> None:
        self._apply_size(self.size)
        self._begin_planning(fresh=True)
        self.order_panel.focus()

    def on_resize(self, event: events.Resize) -> None:
        # ``self.size`` lags the event by a timer tick.
        self._apply_size(event.size)

    def _apply_size(self, size: Size) -> None:
        self._too_small = size.width < MIN_SIZE[0] or size.height < MIN_SIZE[1]
        for widget_id in ("#header", "#body", "#log"):
            self.query_one(widget_id).display = not self._too_small
        self.query_one("#too-small").display = self._too_small
        self.query_one("#side").set_class(size.width < WIDE_COLUMNS, "-narrow")

    # ── state machine ───────────────────────────────────────────────

    def terminal_outcome(self) -> BattleOutcome | None:
        state = self.session.state
        player_alive = any(
            state.ships[ship_id].alive for ship_id in state.player_ships[self.session.player_id]
        )
        enemy_alive = any(state.ships[ship_id].alive for ship_id in self.session.enemy_runtime_ids)
        if not player_alive:
            return BattleOutcome.DEFEAT
        if not enemy_alive:
            return BattleOutcome.VICTORY
        if state.turn >= self.turn_limit:
            return BattleOutcome.TURN_LIMIT
        return None

    def _begin_planning(self, *, fresh: bool) -> None:
        if fresh:
            outcome = self.terminal_outcome()
            if outcome is not None:
                self._stop_timer()
                self.exit(outcome)
                return
            self.draft.commands.clear()
            self.draft.stances.clear()
            self.draft.ability = None
        self.phase = PLANNING
        self._snapshot = snapshot_for(
            self.session.state, self.session.player_id, "start", labels=self._labels
        )
        tmap = self.tactical_map
        tmap.set_zoom_keys_enabled(True)
        tmap.show_snapshot(self._snapshot)
        self.status_panel.set_snapshot(self._snapshot, set(self.draft.commands))
        alive = alive_player_ids(self.session)
        if self.selected not in alive:
            self.selected = None
        self.select_ship(self.selected or (alive[0] if alive else None))
        self._update_header()

    def select_ship(self, ship_id: str | None) -> None:
        self.selected = ship_id
        self.tactical_map.select(ship_id)
        self.status_panel.set_selected(ship_id)
        self.order_panel.set_ship(ship_id)
        self.tactical_map.clear_preview()
        self._update_overlay()

    def _resolve(self) -> None:
        result = finalize(self.draft, self.session)
        if isinstance(result, str):
            self.notify(result, title="Orders rejected", severity="warning")
            return
        commands, stances, ability = result
        state = self.session.state
        self.phase = RESOLVING
        for ship_id, stance in stances.items():
            if not state.ships[ship_id].switch_stance(stance):
                self.phase = PLANNING
                self.notify(f"{state.ships[ship_id].name}: stance rejected.", severity="warning")
                return
        state.advance_turn()
        ai_commands = self.ai.generate_commands(
            state, controlled_ids=self.session.enemy_runtime_ids
        )
        ability_orders = {self.session.player_id: ability} if ability else {}
        snapshots: dict[str, BattleSnapshot] = {}

        def capture(phase: str, phase_state: GameState) -> None:
            snapshots[phase] = snapshot_for(
                phase_state, self.session.player_id, phase, labels=self._labels
            )

        log = resolve_turn(state, commands | ai_commands, ability_orders, on_phase=capture)
        for phase in PHASES:  # a resolver that skipped the hook still animates
            if phase not in snapshots:
                capture(phase, state)
        self.timeline = TimelineBuilder(snapshots, log, self.session.player_id).build()
        final = self.timeline.sample(self.timeline.duration)
        self.history.append((state.turn, list(final.log_lines)))
        self.last_report = build_turn_report(snapshots, log, self.session.player_id)
        self._log_base = [*self.event_log.entries, turn_separator(state.turn)]
        self._start_playback(replay=False)

    # ── playback ────────────────────────────────────────────────────

    def _start_playback(self, *, replay: bool) -> None:
        assert self.timeline is not None
        self._stop_timer()
        self.phase = PLAYBACK
        self._replaying = replay
        self.playhead = 0.0
        tmap = self.tactical_map
        tmap.set_zoom_keys_enabled(False)
        tmap.clear_preview()
        self.event_log.set_lines(self._log_base)
        self._log_shown = 0
        self._show_at(0.0)
        self._last_tick = time.monotonic()
        self._timer = self.set_interval(1 / FPS, self._tick)
        self._update_header()

    def _tick(self) -> None:
        if self.timeline is None or self.phase != PLAYBACK:
            return
        now = time.monotonic()
        self.playhead += (now - self._last_tick) * self.speed
        self._last_tick = now
        if self.playhead >= self.timeline.duration:
            self._finish_playback()
        else:
            self._show_at(self.playhead)

    def _show_at(self, t: float) -> None:
        assert self.timeline is not None
        frame = self.timeline.sample(t)
        self.tactical_map.show_frame(frame)
        self.status_panel.set_bars(frame.bars)
        log = self.event_log
        for line in frame.log_lines[self._log_shown :]:
            log.append(line)
        self._log_shown = max(self._log_shown, len(frame.log_lines))

    def _finish_playback(self) -> None:
        assert self.timeline is not None
        self._stop_timer()
        self.playhead = self.timeline.duration
        self._show_at(self.timeline.duration)
        if self._replaying:
            self._begin_planning(fresh=False)
        elif self.last_report is None or self.terminal_outcome() is not None:
            self._begin_planning(fresh=True)
        else:
            self.push_screen(TurnReportScreen(self.last_report), self._on_report_closed)

    def _on_report_closed(self, _result: None) -> None:
        self._begin_planning(fresh=True)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    # ── actions ─────────────────────────────────────────────────────

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(self.screen, ModalScreen):
            return False
        if action == "confirm_turn":
            return self.phase == PLANNING and self.order_panel.mode == "menu"
        if action == "cycle_ship":
            return self.phase == PLANNING
        if action == "order":
            return self.phase == PLANNING and self.selected is not None
        if action == "skip":
            return self.phase == PLAYBACK
        if action == "log":
            return self.phase == PLANNING
        if action == "replay":
            return self.timeline is not None and self.phase in (PLANNING, PLAYBACK)
        return True

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_log(self) -> None:
        self.push_screen(LogScreen(self.history, self.last_report))

    def action_confirm_turn(self) -> None:
        self.push_screen(
            ConfirmTurnScreen(format_pending(self.session, self.draft, labels=self._labels)),
            self._on_confirmed,
        )

    def _on_confirmed(self, resolve: bool | None) -> None:
        if resolve and self.phase == PLANNING:
            self._resolve()

    def action_order(self, name: str) -> None:
        panel = self.order_panel
        panel.focus()
        getattr(panel, f"action_{name}")()

    def action_cycle_ship(self, step: int) -> None:
        alive = alive_player_ids(self.session)
        if not alive:
            return
        index = alive.index(self.selected) if self.selected in alive else -step
        self.select_ship(alive[(index + step) % len(alive)])

    def action_skip(self) -> None:
        self._finish_playback()

    def action_replay(self) -> None:
        self._start_playback(replay=self.phase == PLANNING or self._replaying)

    def action_faster(self) -> None:
        self._change_speed(1)

    def action_slower(self) -> None:
        self._change_speed(-1)

    def _change_speed(self, step: int) -> None:
        if self.phase != PLAYBACK:
            if step > 0:
                self.tactical_map.action_zoom_in()
            else:
                self.tactical_map.action_zoom_out()
            return
        index = SPEEDS.index(self.speed) + step
        self.speed = SPEEDS[min(max(index, 0), len(SPEEDS) - 1)]
        self._update_header()

    def action_fit(self) -> None:
        self.tactical_map.fit_all()

    def action_center(self) -> None:
        self.tactical_map.center_on_selected()

    def action_overlay(self, overlay: str) -> None:
        self._update_overlay()
        self.tactical_map.toggle_overlay(overlay)

    def action_toggle_side(self) -> None:
        self.query_one("#side").toggle_class("-open")

    def action_request_quit(self) -> None:
        self.push_screen(QuitScreen(), self._on_quit)

    def _on_quit(self, outcome: BattleOutcome | None) -> None:
        if outcome is not None:
            self._stop_timer()
            self.exit(outcome)

    # ── widget messages ─────────────────────────────────────────────

    def on_ship_selected(self, message: ShipSelected) -> None:
        if self.phase == PLANNING and message.ship_id in alive_player_ids(self.session):
            self.select_ship(message.ship_id)

    def on_tactical_map_ship_clicked(self, message: TacticalMap.ShipClicked) -> None:
        if self.phase != PLANNING:
            return
        if message.ship_id in alive_player_ids(self.session):
            self.select_ship(message.ship_id)
            return
        view = self.tactical_map.ship(message.ship_id)
        if view is not None:  # aim / place an ability on a contact
            self.order_panel.handle_map_click(view.position)

    def on_tactical_map_map_clicked(self, message: TacticalMap.MapClicked) -> None:
        if self.phase == PLANNING:
            self.order_panel.handle_map_click(message.world_pos)

    def on_preview_changed(self, message: PreviewChanged) -> None:
        if self.phase == PLANNING:
            self.tactical_map.set_preview(message.kind, message.data)

    def on_preview_cleared(self, message: PreviewCleared) -> None:
        self.tactical_map.clear_preview()

    def on_order_set(self, message: OrderSet) -> None:
        self.status_panel.set_ordered(set(self.draft.commands))
        self._update_overlay()
        self._update_header()

    def on_maneuver_set(self, message: ManeuverSet) -> None:
        self._update_overlay()

    def on_stance_set(self, message: StanceSet) -> None:
        self._update_header()

    def on_ability_set(self, message: AbilitySet) -> None:
        self._update_header()

    # ── helpers ─────────────────────────────────────────────────────

    def _update_overlay(self) -> None:
        if self.selected is None:
            return
        ship = self.session.state.ships[self.selected]
        self.tactical_map.set_overlay_data(
            ship.id,
            arcs=weapon_arcs(ship),
            sensor=sensor_rings(ship, self.session.state),
            drift=drift_prediction(ship, self.draft.maneuvers.get(ship.id), self.session.state),
        )

    def _update_header(self) -> None:
        state = self.session.state
        own = state.player_ships[self.session.player_id]
        alive = len(alive_player_ids(self.session))
        contacts = 0
        if self._snapshot is not None:
            contacts = sum(1 for s in self._snapshot.ships if not s.is_player and s.alive)
        parts = [
            f"Turn {state.turn}/{self.turn_limit}",
            self.phase,
            f"Fleet {alive}/{len(own)}",
            f"Contacts {contacts}",
        ]
        if self.phase == PLAYBACK:
            parts.append(f"Speed {self.speed:g}×")
        else:
            parts.append(f"Orders {len(self.draft.commands)}/{alive}")
        self.query_one("#header", Static).update(" · ".join(parts))


# ── overlay geometry ────────────────────────────────────────────────


def weapon_arcs(ship: Ship) -> list[ArcSpec]:
    """One sector per distinct (arc, range), in absolute compass degrees."""
    seen: set[tuple[Arc, float]] = set()
    arcs: list[ArcSpec] = []
    for mount in ship.weapons:
        key = (mount.arc, mount.weapon.range)
        if key in seen:
            continue
        seen.add(key)
        start, end = _ARC_SPANS[mount.arc]
        arcs.append(
            (
                (ship.heading + start) % 360.0,
                (ship.heading + end) % 360.0,
                mount.weapon.range,
                _ARC_STYLES[mount.arc],
            )
        )
    return arcs


def sensor_rings(ship: Ship, state: GameState) -> tuple[float, float, float]:
    """BLIP, CONTACT and IDENTIFIED radii (GU) around *ship*."""
    reach = effective_sensor_range(ship, state)
    reach *= StanceRegistry.get_for(ship.stance).own_sensor_range_modifier
    return reach * 1.5, reach, reach * 0.75


def drift_prediction(
    ship: Ship, maneuver: Maneuver | None, state: GameState
) -> tuple[float, Vector2D, Vector2D]:
    """``(heading, end, mid)``: where *ship* ends the turn under *maneuver*,
    passing through *mid* halfway."""
    prediction = predict_move(ship, maneuver, state=state)
    return prediction.end_heading, prediction.end, prediction.mid


# ── runners ─────────────────────────────────────────────────────────


def run_battle(
    session: BattleSession,
    *,
    turn_limit: int = TURN_LIMIT,
    ai: AIController | None = None,
) -> BattleOutcome:
    result = BattleApp(session, turn_limit=turn_limit, ai=ai).run()
    return BattleOutcome.ABANDONED if result is None else result


class TuiBattleRunner:
    """:class:`BattleRunner` that runs :class:`BattleApp`, off the menu screen."""

    def __init__(
        self,
        session: BattleSession,
        ui: TerminalUI | None = None,
        *,
        turn_limit: int = TURN_LIMIT,
        ai: AIController | None = None,
    ) -> None:
        self.session = session
        self.ui = ui
        self.turn_limit = turn_limit
        self.ai = ai

    def run(self) -> BattleOutcome:
        if self.ui is None:
            return run_battle(self.session, turn_limit=self.turn_limit, ai=self.ai)
        with self.ui.suspended():
            return run_battle(self.session, turn_limit=self.turn_limit, ai=self.ai)
