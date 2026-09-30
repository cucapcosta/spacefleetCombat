"""Per-ship order panel: a free maneuver plus one action.

The Maneuver section is always shown at the top for the selected ship.  At
the top menu the arrow keys edit it (↑/↓ speed, ←/→ turn in 15° steps up to
``Ship.max_turn_this_turn`` at the new speed); inside a submenu the arrows
navigate its options as usual.  Top-menu actions are picked by their letter
keys (or a click): Fire / Boarding strike / Tactic / Ability / Pass.

The panel edits an :class:`OrderDraft` in place and reports through messages:
previews for the map while the player is choosing, :class:`ManeuverSet` when
the maneuver changes, :class:`OrderSet` once a ship's action is validated.
Rejections from the order validators are shown inline and never reach the
draft.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, ClassVar, cast

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from spacefleet.combat.fire_control import bearing_spread
from spacefleet.core.types import Stance
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.spatial.geometry import arc_name, arc_range_str, relative_bearing_360
from spacefleet.tui.model.orders import (
    Aim,
    Shot,
    ability_order,
    ability_ship_targets,
    ability_targeting,
    blocker_summary,
    contact_aims,
    contact_blockers,
    fire_unavailable_reason,
    hostile_contacts,
    predict_move,
    relative_to,
    stance_rejection,
    validated_command,
    validated_fire_salvo,
    validated_maneuver,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.core.types import Vector2D
    from spacefleet.models.ship import Ship
    from spacefleet.net.commands import AbilityOrder, Command
    from spacefleet.spatial.detection import ContactInfo
    from spacefleet.tui.model.orders import OrderDraft

TURN_STEP = 15.0
SPEED_STEP = 1.0
SUBSYSTEMS = ("generator", "deck", "engines", "weapons")

# mode -> the mode Esc returns to
_PARENT = {
    "fire_target": "menu",
    "fire_manual": "fire_target",
    "fire_weapons": "fire_target",
    "strike_target": "menu",
    "strike_subsystem": "strike_target",
    "tactic": "menu",
    "ability": "menu",
    "ability_ship": "ability",
    "ability_pos": "ability",
}


class PreviewChanged(Message):
    """Something the map should draw while an order is being chosen.

    ``kind`` is ``"route"`` (ship_id, pos, heading, path through the
    mid-turn point), ``"aim"``
    (ship_id, origin, bearing_abs, spread_deg, range) or ``"strike"`` (targets).
    """

    def __init__(self, kind: str, data: dict[str, Any]) -> None:
        super().__init__()
        self.kind = kind
        self.data = data


class PreviewCleared(Message):
    """The previous preview no longer applies."""


class OrderSet(Message):
    """*ship_id* now has a validated action in the draft."""

    def __init__(self, ship_id: str) -> None:
        super().__init__()
        self.ship_id = ship_id


class ManeuverSet(Message):
    """*ship_id*'s maneuver in the draft changed (possibly back to none)."""

    def __init__(self, ship_id: str) -> None:
        super().__init__()
        self.ship_id = ship_id


class StanceSet(Message):
    def __init__(self, ship_id: str, stance: Stance) -> None:
        super().__init__()
        self.ship_id = ship_id
        self.stance = stance


class AbilitySet(Message):
    """The fleet's commander ability for this turn (None clears it)."""

    def __init__(self, order: AbilityOrder | None) -> None:
        super().__init__()
        self.order = order


class AbilityNeedsPosition(Message):
    """The panel waits for :meth:`OrderPanel.set_ability_position` (a map click)."""

    def __init__(self, ability_id: str) -> None:
        super().__init__()
        self.ability_id = ability_id


class OrderPanel(Widget, can_focus=True):
    DEFAULT_CSS = """
    OrderPanel { height: auto; }
    OrderPanel > Vertical { height: auto; }
    OrderPanel #op-title { text-style: bold; }
    OrderPanel #op-maneuver { color: $accent; }
    OrderPanel #op-order { color: $text-muted; }
    OrderPanel #op-error { color: $error; }
    OrderPanel OptionList { height: auto; max-height: 16; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "maneuver(1, 0)", "Speed", show=False, priority=True),
        Binding("down", "maneuver(-1, 0)", "Speed", show=False, priority=True),
        Binding("left", "maneuver(0, -1)", "Turn", show=False, priority=True),
        Binding("right", "maneuver(0, 1)", "Turn", show=False, priority=True),
        Binding("f", "fire", "Fire"),
        Binding("b", "strike", "Board"),
        Binding("t", "tactic", "Tactic"),
        Binding("h", "ability", "Ability"),
        Binding("p", "pass", "Pass"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(
        self,
        session: BattleSession,
        draft: OrderDraft,
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - Textual's keyword
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.session = session
        self.draft = draft
        self.ship_id: str | None = None
        self.mode = "menu"
        self.error_text = ""
        self._shown_mode = ""
        self._reset_ship_state()

    def _reset_ship_state(self) -> None:
        self._contacts: list[ContactInfo] = []
        self._shots: list[Shot] = []
        self._used_slots: set[int] = set()
        self._aims: dict[int, Aim] = {}
        self._selected: set[int] = set()
        self._aim_title = ""
        self._strike_target: str | None = None
        self._ability_id: str | None = None
        self._ability_ship: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="op-title", markup=False)
            yield Static(id="op-maneuver", markup=False)
            yield Static(id="op-order", markup=False)
            yield Static(id="op-editor", markup=False)
            yield OptionList(id="op-options")
            yield Input(id="op-bearing", placeholder="Bearing rel. to prow (0 ahead, 90 stbd)")
            yield Static(id="op-error", markup=False)

    def on_mount(self) -> None:
        self._refresh()

    # ── public API ──────────────────────────────────────────────────

    @property
    def ship(self) -> Ship | None:
        return None if self.ship_id is None else self.session.state.ships[self.ship_id]

    def set_ship(self, ship_id: str | None) -> None:
        if ship_id != self.ship_id:
            self.post_message(PreviewCleared())
        self.ship_id = ship_id
        self._reset_ship_state()
        self.mode = "menu"
        self.error_text = ""
        self._refresh()

    def choose(self, option_id: str) -> None:
        """Act on the option *option_id* of the current menu (Enter or click)."""
        ship = self.ship
        if ship is None:
            return
        handler = getattr(self, f"_choose_{self.mode}", None)
        if handler is not None:
            self.error_text = ""
            handler(ship, option_id)
            self._refresh()

    def option_labels(self) -> list[str]:
        options = self.query_one("#op-options", OptionList)
        return [str(cast("Text", option.prompt).plain) for option in options.options]

    def set_manual_bearing(self, bearing: float) -> None:
        """Aim every weapon at *bearing* (prow-relative) and pick weapons."""
        ship = self.ship
        if ship is None or not math.isfinite(bearing):
            return
        bearing %= 360.0
        self._aims = {mount.slot_id: Aim(bearing, None) for mount in ship.weapons}
        self._selected = set()
        self._aim_title = f"Weapons at bearing {bearing:g}° rel"
        self.mode = "fire_weapons"
        self.error_text = ""
        self._preview_bearing(ship, bearing)
        self._refresh()

    def handle_map_click(self, world_pos: Vector2D) -> None:
        ship = self.ship
        if ship is None:
            return
        if self.mode == "fire_manual" or (self.mode == "fire_weapons" and self._manual_aims()):
            self.set_manual_bearing(round(relative_to(ship, world_pos), 1))
        elif self.mode == "ability_pos":
            self.set_ability_position(world_pos)

    def set_ability_position(self, position: Vector2D) -> None:
        if self.mode != "ability_pos" or self._ability_id is None:
            return
        self._finish_ability(self._ability_id, self._ability_ship, position)
        self._refresh()

    # ── actions ─────────────────────────────────────────────────────

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "maneuver":
            # Outside the top menu the arrows belong to the submenu's options.
            return self.ship is not None and self.mode == "menu"
        if action in {"fire", "strike", "tactic", "ability", "pass"}:
            return self.ship is not None
        return True

    def action_maneuver(self, speed_steps: int, turn_steps: int) -> None:
        """Step the selected ship's speed and/or turn; clamp to what it can do."""
        ship = self.ship
        if ship is None:
            return
        speed, turn = self._maneuver_values(ship)
        if speed_steps:
            top = max(ship.effective_speed_max, ship.speed)
            speed = min(max(speed + speed_steps * SPEED_STEP, 0.0), top)
        limit = ship.max_turn_this_turn(speed)
        turn = min(max(turn + turn_steps * TURN_STEP, -limit), limit)
        self._set_maneuver(ship, speed, turn)
        self._refresh()

    def action_fire(self) -> None:
        if self.ship is None:
            return
        self._shots = []
        self._used_slots = set()
        self._enter("fire_target")
        self._refresh()

    def action_tactic(self) -> None:
        self._enter("tactic")
        self._refresh()

    def action_ability(self) -> None:
        self._enter("ability")
        self._refresh()

    def action_pass(self) -> None:
        ship = self.ship
        if ship is None:
            return
        self._commit(ship, validated_command(self.session, ship, ["pass"]))
        self._refresh()

    def action_strike(self) -> None:
        self._enter("strike_target")
        self._refresh()

    def action_back(self) -> None:
        parent = _PARENT.get(self.mode)
        if parent is None:
            return
        self.error_text = ""
        self.post_message(PreviewCleared())
        if parent == "fire_target":
            self._selected = set()
        self.mode = parent
        self._refresh()

    # ── events ──────────────────────────────────────────────────────

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id is not None:
            self.choose(event.option.id)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        ship = self.ship
        option_id = event.option.id
        if ship is None or option_id is None:
            return
        if self.mode == "fire_weapons" and option_id.startswith("slot:"):
            self._preview_slot(ship, int(option_id.removeprefix("slot:")))
        elif self.mode == "fire_target" and option_id.startswith("contact:"):
            contact = self._contacts[int(option_id.removeprefix("contact:"))]
            aims = contact_aims(self.session, ship, contact)
            slot = next((s for s, aim in aims.items() if aim.bearing is not None), None)
            if slot is not None:
                self._aims = aims
                self._preview_slot(ship, slot)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        try:
            bearing = float(event.value)
        except ValueError:
            self.error_text = "Invalid bearing: enter a number."
            self._refresh()
            return
        if not math.isfinite(bearing):
            self.error_text = "Invalid bearing: value must be finite."
            self._refresh()
            return
        self.set_manual_bearing(bearing)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        ship = self.ship
        try:
            bearing = float(event.value)
        except ValueError:
            return
        if ship is not None and math.isfinite(bearing):
            self._preview_bearing(ship, bearing % 360.0)

    # ── menu handlers (``_choose_<mode>``) ──────────────────────────

    def _choose_menu(self, ship: Ship, option_id: str) -> None:
        action = getattr(self, f"action_{option_id}", None)
        if action is not None:
            action()

    def _choose_fire_target(self, ship: Ship, option_id: str) -> None:
        if option_id == "manual":
            self.mode = "fire_manual"
        elif option_id == "done":
            self._commit(ship, validated_fire_salvo(self.session, ship, self._shots))
        elif option_id == "clear":
            self._shots = []
            self._used_slots = set()
        elif option_id == "back":
            self.action_back()
        elif option_id.startswith("contact:"):
            contact = self._contacts[int(option_id.removeprefix("contact:"))]
            self._aims = contact_aims(self.session, ship, contact)
            self._selected = set()
            self._aim_title = f"Weapons on {contact.display_name}"
            self.mode = "fire_weapons"

    def _choose_fire_weapons(self, ship: Ship, option_id: str) -> None:
        if option_id == "back":
            self.action_back()
            return
        reasons = self._weapon_reasons(ship)
        if option_id == "all":
            self._selected.update(slot for slot, reason in reasons.items() if reason is None)
        elif option_id == "done":
            if not self._selected:
                self.error_text = "Select at least one weapon."
                return
            for mount in ship.weapons:
                if mount.slot_id not in self._selected:
                    continue
                aim = self._aims[mount.slot_id]
                assert aim.bearing is not None
                shot: Shot = {"slot": mount.slot_id, "bearing": aim.bearing}
                if aim.target_id is not None:
                    shot["target"] = aim.target_id
                self._shots.append(shot)
                self._used_slots.add(mount.slot_id)
            self._selected = set()
            self.mode = "fire_target"
            self.post_message(PreviewCleared())
        elif option_id.startswith("slot:"):
            slot = int(option_id.removeprefix("slot:"))
            if slot in self._selected:
                self._selected.remove(slot)
            elif reasons.get(slot) is None:
                self._selected.add(slot)
                self._preview_slot(ship, slot)
            else:
                self.error_text = str(reasons[slot])

    def _choose_strike_target(self, ship: Ship, option_id: str) -> None:
        if option_id == "back":
            self.action_back()
            return
        self._strike_target = option_id.removeprefix("target:")
        self.mode = "strike_subsystem"

    def _choose_strike_subsystem(self, ship: Ship, option_id: str) -> None:
        if option_id == "back" or self._strike_target is None:
            self.action_back()
            return
        tokens = ["strike", self._strike_target, option_id.removeprefix("sub:")]
        self._commit(ship, validated_command(self.session, ship, tokens))

    def _choose_tactic(self, ship: Ship, option_id: str) -> None:
        if option_id == "back":
            self.action_back()
            return
        stance = Stance(option_id.removeprefix("stance:"))
        rejection = stance_rejection(ship, stance)
        if rejection is not None:
            self.error_text = f"Invalid stance: {rejection}"
            return
        self.draft.stances[ship.id] = stance
        self.mode = "menu"
        self.post_message(StanceSet(ship.id, stance))

    def _choose_ability(self, ship: Ship, option_id: str) -> None:
        if option_id == "back":
            self.action_back()
            return
        if option_id == "none":
            self.draft.ability = None
            self.mode = "menu"
            self.post_message(AbilitySet(None))
            return
        ability_id = option_id.removeprefix("ability:")
        self._ability_id = ability_id
        self._ability_ship = None
        needs_ship, needs_pos = ability_targeting(ability_id)
        if needs_ship:
            self.mode = "ability_ship"
        elif needs_pos:
            self._await_position(ability_id)
        else:
            self._finish_ability(ability_id, None, None)

    def _choose_ability_ship(self, ship: Ship, option_id: str) -> None:
        if option_id == "back" or self._ability_id is None:
            self.action_back()
            return
        self._ability_ship = option_id.removeprefix("target:")
        if ability_targeting(self._ability_id)[1]:
            self._await_position(self._ability_id)
        else:
            self._finish_ability(self._ability_id, self._ability_ship, None)

    def _choose_ability_pos(self, ship: Ship, option_id: str) -> None:
        if option_id == "back":
            self.action_back()

    # ── helpers ─────────────────────────────────────────────────────

    def _enter(self, mode: str) -> None:
        if self.mode != "menu":
            self.post_message(PreviewCleared())
        self.mode = mode
        self.error_text = ""

    def _commit(self, ship: Ship, command: Command | str) -> None:
        if isinstance(command, str):
            self.error_text = f"Invalid: {command}"
            return
        self.draft.commands[ship.id] = command
        self.mode = "menu"
        self.error_text = ""
        self.post_message(PreviewCleared())
        self.post_message(OrderSet(ship.id))

    def _await_position(self, ability_id: str) -> None:
        self.mode = "ability_pos"
        self.post_message(AbilityNeedsPosition(ability_id))

    def _finish_ability(
        self, ability_id: str, target_ship: str | None, position: Vector2D | None
    ) -> None:
        order = ability_order(
            self.session, ability_id, target_ship_id=target_ship, target_position=position
        )
        if isinstance(order, str):
            self.error_text = f"Invalid ability: {order}"
            return
        self.draft.ability = order
        self.mode = "menu"
        self.error_text = ""
        self.post_message(AbilitySet(order))

    def _maneuver_values(self, ship: Ship) -> tuple[float, float]:
        """``(speed after, signed turn)`` of the drafted maneuver; default holds course."""
        maneuver = self.draft.maneuvers.get(ship.id)
        if maneuver is None:
            return ship.speed, 0.0
        speed = ship.speed if maneuver.speed is None else maneuver.speed
        return speed, maneuver.turn

    def _set_maneuver(self, ship: Ship, speed: float, turn: float) -> None:
        target = None if speed == ship.speed else speed
        if target is None and not turn:
            self.draft.maneuvers.pop(ship.id, None)
        else:
            maneuver = validated_maneuver(self.session, ship, target, turn)
            if isinstance(maneuver, str):
                self.error_text = f"Invalid maneuver: {maneuver}"
                return
            self.draft.maneuvers[ship.id] = maneuver
        self.error_text = ""
        self.post_message(ManeuverSet(ship.id))
        self._preview_route(ship)

    def _manual_aims(self) -> bool:
        return bool(self._aims) and all(aim.target_id is None for aim in self._aims.values())

    def _weapon_reasons(self, ship: Ship) -> dict[int, str | None]:
        return {
            mount.slot_id: fire_unavailable_reason(
                self.session,
                ship,
                mount.slot_id,
                aim=self._aims.get(mount.slot_id, Aim(None, None)),
                used_slots=self._used_slots,
            )
            for mount in ship.weapons
        }

    # ── previews ────────────────────────────────────────────────────

    def _preview_route(self, ship: Ship) -> None:
        prediction = predict_move(ship, self.draft.maneuvers.get(ship.id), state=self.session.state)
        self.post_message(
            PreviewChanged(
                "route",
                {
                    "ship_id": ship.id,
                    "pos": prediction.end,
                    "heading": prediction.end_heading,
                    "path": prediction.path,
                },
            )
        )

    def _preview_slot(self, ship: Ship, slot: int) -> None:
        aim = self._aims.get(slot)
        if aim is None or aim.bearing is None:
            return
        mount = next(mount for mount in ship.weapons if mount.slot_id == slot)
        spread = (
            bearing_spread(ship, mount, self.session.state, aim.lock)
            if mount.weapon.speed > 0
            else 0.0
        )
        self._post_aim(ship, aim.bearing, spread, mount.weapon.range)

    def _preview_bearing(self, ship: Ship, bearing: float) -> None:
        reach = max((mount.weapon.range for mount in ship.weapons), default=0.0)
        self._post_aim(ship, bearing, 0.0, reach)

    def _post_aim(self, ship: Ship, bearing: float, spread: float, reach: float) -> None:
        self.post_message(
            PreviewChanged(
                "aim",
                {
                    "ship_id": ship.id,
                    "origin": ship.position,
                    "bearing_abs": (ship.heading + bearing) % 360.0,
                    "spread_deg": spread,
                    "range": reach,
                },
            )
        )

    # ── rendering ───────────────────────────────────────────────────

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        ship = self.ship
        title = self.query_one("#op-title", Static)
        maneuver = self.query_one("#op-maneuver", Static)
        order = self.query_one("#op-order", Static)
        editor = self.query_one("#op-editor", Static)
        options = self.query_one("#op-options", OptionList)
        bearing_input = self.query_one("#op-bearing", Input)
        error = self.query_one("#op-error", Static)

        if ship is None:
            title.update("No ship selected")
            maneuver.update("")
            order.update("")
            editor.update("")
            options.clear_options()
            bearing_input.display = False
            error.update("")
            return

        marker = "✓" if ship.id in self.draft.commands else "·"
        title.update(f"▸ {ship.name}  [order {marker}]")
        maneuver.update(self._maneuver_text(ship))
        order.update(self._order_summary(ship))
        editor.update(self._editor_text(ship))
        error.update(self.error_text)

        rows = self._options(ship)
        previous = options.highlighted if self._shown_mode == self.mode else None
        self._shown_mode = self.mode
        options.set_options(rows)
        # set_options drops the highlight; without one, Enter selects nothing.
        # Keep the cursor in place while the same menu is rebuilt.
        enabled = [
            i for i in range(options.option_count) if not options.get_option_at_index(i).disabled
        ]
        start = previous or 0
        options.highlighted = next(
            (i for i in enabled if i >= start), enabled[0] if enabled else None
        )
        bearing_input.display = self.mode == "fire_manual"
        if self.mode == "fire_manual":
            bearing_input.value = ""
            bearing_input.focus()
        elif rows and (self.has_focus or bearing_input.has_focus or options.has_focus):
            options.focus()

    def _order_summary(self, ship: Ship) -> str:
        command = self.draft.commands.get(ship.id)
        text = "Order: " + ("none" if command is None else self._describe(ship, command))
        stance = self.draft.stances.get(ship.id)
        if stance is not None:
            text += f"; stance {stance.value.replace('_', ' ').title()}"
        return text

    def _describe(self, ship: Ship, command: Command) -> str:
        args = command.args
        if command.action == "pass":
            return "Wait"
        if command.action == "strike":
            return f"Board {args['target']}; target {args['subsystem']}"
        shots = cast("list[Shot]", args.get("shots", [args]))
        return "Fire " + ", ".join(
            f"slot {int(shot['slot'])} @ {float(shot['bearing']):g}°" for shot in shots
        )

    def _maneuver_text(self, ship: Ship) -> str:
        speed, turn = self._maneuver_values(ship)
        side = "port" if turn < 0 else "starboard"
        turn_text = f"{abs(turn):g}° {side}" if turn else "none"
        limit = ship.max_turn_this_turn(speed)
        speed_keys, turn_keys = ("  [↑/↓]", "  [←/→]") if self.mode == "menu" else ("", "")
        return (
            f"Speed {ship.speed:g} → {speed:g} GU/turn{speed_keys}\n"
            f"Turn {turn_text} (max {limit:g}° this turn){turn_keys}"
        )

    def _editor_text(self, ship: Ship) -> str:
        if self.mode == "fire_target":
            return f"Fire salvo — {len(self._shots)} shot(s) queued"
        if self.mode == "fire_manual":
            return "Type a bearing or click the map."
        if self.mode == "fire_weapons":
            return self._aim_title
        if self.mode == "ability_pos":
            return "Click the map to choose the target position.  [Esc] back"
        if self.mode == "menu":
            return "[F]ire [B]oard [T]actic [H]ability [P]ass"
        return ""

    def _options(self, ship: Ship) -> list[Option]:
        builder = getattr(self, f"_options_{self.mode}", None)
        return [] if builder is None else cast("list[Option]", builder(ship))

    def _options_menu(self, ship: Ship) -> list[Option]:
        strike_reason = None if ship.hull.assault_actions > 0 else "no boarding capability"
        return [
            _option("fire", "[F] Fire"),
            _option("strike", "[B] Boarding strike", strike_reason),
            _option("tactic", "[T] Tactic"),
            _option("ability", "[H] Ability"),
            _option("pass", "[P] Pass"),
        ]

    def _options_fire_target(self, ship: Ship) -> list[Option]:
        self._contacts = hostile_contacts(self.session, ship)
        rows = []
        for index, contact in enumerate(self._contacts):
            blockers = contact_blockers(self.session, ship, contact, self._used_slots)
            ready = sum(1 for blocker in blockers.values() if blocker is None)
            label = f"{contact.display_name} [{contact.detection_level.name.lower()}]"
            if ready:
                rows.append(_option(f"contact:{index}", f"{label} — {ready}/{len(blockers)} ready"))
            else:
                reason = f"no firing solution: {blocker_summary(blockers)}"
                rows.append(_option(f"contact:{index}", label, reason))
        rows.append(_option("manual", "Manual bearing (type or click map)"))
        if self._shots:
            rows.append(_option("done", f"Done — queue salvo ({len(self._shots)} shot(s))"))
            rows.append(_option("clear", "Clear queued salvo"))
        rows.append(_option("back", "Cancel fire"))
        return rows

    def _options_fire_weapons(self, ship: Ship) -> list[Option]:
        reasons = self._weapon_reasons(ship)
        rows = []
        for mount in ship.weapons:
            box = "[x]" if mount.slot_id in self._selected else "[ ]"
            detail = f"{arc_name(mount.arc)} {arc_range_str(mount.arc)}, {mount.weapon.range:g} GU"
            aim = self._aims.get(mount.slot_id)
            if aim is not None and aim.bearing is not None:
                detail += f"; aim {aim.bearing:.0f}° rel"
            rows.append(
                _option(
                    f"slot:{mount.slot_id}",
                    f"{box} {mount.display_name} — {detail}",
                    reasons[mount.slot_id],
                )
            )
        eligible = any(r is None and s not in self._selected for s, r in reasons.items())
        rows.append(_option("all", "Add all eligible", None if eligible else "none left"))
        rows.append(
            _option("done", "Done with this aim", None if self._selected else "select a weapon")
        )
        rows.append(_option("back", "Back"))
        return rows

    def _options_strike_target(self, ship: Ship) -> list[Option]:
        contacts = hostile_contacts(self.session, ship)
        if self._shown_mode != "strike_target":
            targets = [contact.ship.id for contact in contacts]
            self.post_message(PreviewChanged("strike", {"targets": targets}))
        rows = []
        for contact in contacts:
            bearing = relative_bearing_360(ship.heading, contact.true_bearing)
            rows.append(
                _option(
                    f"target:{contact.ship.id}",
                    f"{contact.display_name} — {bearing:.0f}° rel, {contact.true_distance:.1f} GU",
                )
            )
        rows.append(_option("back", "Back"))
        return rows

    def _options_strike_subsystem(self, ship: Ship) -> list[Option]:
        rows = [_option(f"sub:{name}", name.title()) for name in SUBSYSTEMS]
        rows.append(_option("back", "Back"))
        return rows

    def _options_tactic(self, ship: Ship) -> list[Option]:
        chosen = self.draft.stances.get(ship.id, ship.stance)
        rows = []
        for stance in Stance:
            mark = "●" if stance is chosen else " "
            label = f"{mark} {stance.value.replace('_', ' ').title()}"
            rows.append(_option(f"stance:{stance.value}", label, stance_rejection(ship, stance)))
        rows.append(_option("back", "Back"))
        return rows

    def _options_ability(self, ship: Ship) -> list[Option]:
        rows = [_option("none", "None this turn")]
        commander = self.session.state.fleets[self.session.player_id].commander
        for ability_id in commander.active_ability_ids if commander is not None else []:
            definition = SkillRegistry.get_active(ability_id)
            if definition is None:
                continue
            assert commander is not None
            runtime = commander.ability_state.get(ability_id)
            charges = runtime.remaining_charges if runtime else definition.charges
            cooldown = runtime.cooldown_remaining if runtime else 0
            reason = None
            if charges <= 0:
                reason = "no charges remaining"
            elif max(0, cooldown - 1) > 0:
                reason = f"cooldown {cooldown - 1} turn(s)"
            rows.append(
                _option(f"ability:{ability_id}", f"{definition.name} (charges {charges})", reason)
            )
        rows.append(_option("back", "Back"))
        return rows

    def _options_ability_ship(self, ship: Ship) -> list[Option]:
        assert self._ability_id is not None
        rows = [
            _option(f"target:{ship_id}", label)
            for ship_id, label in ability_ship_targets(self.session, self._ability_id)
        ]
        rows.append(_option("back", "Back"))
        return rows

    def _options_ability_pos(self, ship: Ship) -> list[Option]:
        return [_option("back", "Back")]


def _option(option_id: str, label: str, reason: str | None = None) -> Option:
    """An option whose disabled *reason* is shown inline."""
    text = Text(label)
    if reason is not None:
        text.append(f" — {reason}", style="red")
    return Option(text, id=option_id, disabled=reason is not None)
