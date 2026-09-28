"""Synchronous local controller for campaign battles."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from spacefleet.campaign.models import BattleOutcome
from spacefleet.cli.action_parser import parse_action_command
from spacefleet.cli.terminal_ui import MenuOption, TerminalClosed, TerminalUI
from spacefleet.combat.fire_control import aim_for, bearing_spread, hit_probability
from spacefleet.commander.abilities import (
    AbilityUsedEvent,
    AreaHullDamage,
    AreaMoraleDamage,
    BonusBoardingAssault,
    ConcentratedFireBuff,
    SpawnProbe,
    Teleport,
)
from spacefleet.core.types import DetectionLevel, Stance, Vector2D
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.net.ai_controller import AIController
from spacefleet.net.commands import AbilityOrder, Command, validate_command
from spacefleet.net.server_renderer import ServerRenderer
from spacefleet.net.turn_resolver import TurnLog, resolve_turn
from spacefleet.phases.command_phase import (
    AbilityInterruptedEvent,
    AbilityPrepStartedEvent,
    AbilityRejectedEvent,
    validate_ability_order,
)
from spacefleet.spatial.geometry import (
    arc_name,
    arc_range_str,
    bearing_from_to,
    distance,
    relative_bearing_360,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount
    from spacefleet.spatial.detection import ContactInfo


# Every bearing the battle UI shows or accepts uses this convention, the same
# one weapon arcs and fire orders use.
BEARING_HINT = (
    "Bearings are relative to your prow: 0° ahead, 90° starboard, 180° astern, 270° port."
)


@dataclass(frozen=True)
class _Aim:
    """Prow-relative bearing and distance one weapon would fire at.

    A None bearing means no intercept.

    *target_id* locks fire control on a contact; *lock* is how well it is seen.
    Manual bearings carry no lock and fire with the widest spread.
    """

    bearing: float | None
    distance: float | None
    target_id: str | None = None
    lock: DetectionLevel = DetectionLevel.UNDETECTED


@dataclass
class _PendingTurn:
    commands: dict[str, Command] = field(default_factory=dict)
    stances: dict[str, Stance] = field(default_factory=dict)
    ability: AbilityOrder | None = None


class LocalBattleController:
    """Collect, review, and resolve one simultaneous local turn at a time."""

    def __init__(
        self,
        session: BattleSession,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        renderer: ServerRenderer | None = None,
        ai: AIController | None = None,
        turn_limit: int = 60,
        ui: TerminalUI | None = None,
    ) -> None:
        if turn_limit < 1:
            raise ValueError("turn limit must be positive")
        self.session = session
        self.renderer = renderer or ServerRenderer()
        self.ai = ai or AIController()
        self.turn_limit = turn_limit
        self.ui = ui or TerminalUI(input_fn=input_fn, output_fn=output_fn)
        self._scanner_ship: Ship | None = None

    def run(self) -> BattleOutcome:
        """Run until victory, defeat, surrender, turn limit, or abandonment."""
        try:
            with self.ui.session(), self.ui.panel(self._render_scanner):
                return self._run()
        except TerminalClosed:
            return self._abandon()

    def _render_scanner(self, width: int, height: int) -> str:
        observer = self._scanner_ship
        if observer is None:
            alive = self._alive_player_ids()
            observer = self.session.state.ships[alive[0]] if alive else None
        if observer is None:
            return "SCANNER\nNo observing ship available."
        compact = height <= 26
        grid_width = min(31, max(5, (width - 10) // 2))
        grid_height = 5 if compact else min(17, max(5, height - 5))
        grid_width -= (grid_width + 1) % 2
        grid_height -= (grid_height + 1) % 2
        projectile_line = int(
            any(projectile.alive for projectile in self.session.state.projectiles)
        )
        legend_limit = max(1, height - grid_height - 5 - projectile_line) if compact else None
        return self.renderer.preview_scanner(
            observer,
            self.session.state,
            self.session.player_id,
            grid_width=grid_width,
            grid_height=grid_height,
            compact_legend=compact,
            legend_limit=legend_limit,
        )

    def _run(self) -> BattleOutcome:
        while True:
            outcome = self._terminal_outcome()
            if outcome is not None:
                return outcome
            if self.session.state.turn >= self.turn_limit:
                return BattleOutcome.TURN_LIMIT

            pending = self._collect_turn()
            if isinstance(pending, BattleOutcome):
                return pending
            decision = self._review(pending)
            if isinstance(decision, BattleOutcome):
                return decision
            if not decision:
                continue

            for ship_id, stance in pending.stances.items():
                if not self.session.state.ships[ship_id].switch_stance(stance):
                    raise RuntimeError(f"queued stance for {ship_id!r} became invalid")

            state = self.session.state
            state.advance_turn()
            ai_commands = self.ai.generate_commands(
                state, controlled_ids=self.session.enemy_runtime_ids
            )
            ability_orders = {self.session.player_id: pending.ability} if pending.ability else {}
            log = resolve_turn(state, pending.commands | ai_commands, ability_orders)
            self._render_turn(log)

    def _collect_turn(self) -> _PendingTurn | BattleOutcome:
        pending = _PendingTurn()
        for ship_id in self._alive_player_ids():
            outcome = self._collect_ship_order(self.session.state.ships[ship_id], pending)
            if outcome is not None:
                return outcome
        ability = self._collect_ability()
        if isinstance(ability, BattleOutcome):
            return ability
        pending.ability = ability
        return pending

    def _collect_ship_order(self, ship: Ship, pending: _PendingTurn) -> BattleOutcome | None:
        self._scanner_ship = ship
        while True:
            choice = self.ui.choose(
                f"Orders — {ship.name}",
                (
                    MenuOption("attack", "Attack", self._attack_summary(ship)),
                    MenuOption("move", "Move", "Set speed or queue a turn."),
                    MenuOption("tactic", "Tactic", "Change stance or inspect."),
                    MenuOption("wait", "Wait", "Take no ship action."),
                ),
                context=self.renderer.preview_ship_brief(
                    ship, self.session.state, self.session.player_id
                ),
                columns=2,
            )
            if choice is None:
                continue
            if choice == "tactic":
                self._tactic_menu(ship, pending)
                continue
            command = (
                self._attack_menu(ship)
                if choice == "attack"
                else self._move_menu(ship)
                if choice == "move"
                else self._validated_command(ship, ["pass"])
            )
            if command is not None:
                pending.commands[ship.id] = command
                return None

    def _attack_menu(self, ship: Ship) -> Command | None:
        while True:
            choice = self.ui.choose(
                f"Attack — {ship.name}",
                (
                    MenuOption("fire", "Fire"),
                    MenuOption(
                        "boarding",
                        "Boarding strike",
                        disabled_reason=None
                        if ship.hull.assault_actions > 0
                        else "No boarding capability.",
                    ),
                    MenuOption("back", "Back"),
                ),
            )
            if choice in {None, "back"}:
                return None
            if choice == "boarding":
                command = self._boarding_menu(ship)
                if command is not None:
                    return command
                continue
            command = self._fire_menu(ship)
            if command is not None:
                return command

    def _fire_menu(self, ship: Ship) -> Command | None:
        shots: list[dict[str, int | float | str]] = []
        used_slots: set[int] = set()
        while True:
            contacts = [
                contact
                for contact in self.renderer.preview_contacts(
                    ship, self.session.state, self.session.player_id
                )
                if not contact.is_friendly
            ]
            options = [
                self._fire_contact_option(index, ship, contact, used_slots)
                for index, contact in enumerate(contacts)
            ]
            options.append(
                MenuOption(
                    "manual",
                    "Manual bearing",
                    f"Enter any bearing. {BEARING_HINT} No lead is computed.",
                )
            )
            if shots:
                options.extend(
                    (
                        MenuOption("done", "Done — queue salvo", self._format_shots(ship, shots)),
                        MenuOption("clear", "Clear queued salvo"),
                    )
                )
            options.append(MenuOption("back", "Cancel fire"))

            choice = self.ui.choose(
                f"Fire salvo — {ship.name}",
                options,
                context=self._fire_context(ship, contacts, shots),
            )
            if choice in {None, "back"}:
                return None
            if choice == "done":
                return self._validated_fire_salvo(ship, shots)
            if choice == "clear":
                shots.clear()
                used_slots.clear()
                continue
            assert choice is not None

            if choice == "manual":
                self.ui.show(self._manual_fire_context(ship, used_slots))
                raw_bearing = self.ui.text(
                    "Bearing rel. to prow (0 ahead, 90 starboard, 270 port)",
                    "battle.fire.bearing",
                )
                if raw_bearing is None:
                    continue
                try:
                    bearing = float(raw_bearing) % 360.0
                except ValueError:
                    self.ui.show("Invalid bearing: enter a number.")
                    continue
                if not math.isfinite(bearing):
                    self.ui.show("Invalid bearing: value must be finite.")
                    continue
                aims: dict[int, _Aim] = {
                    mount.slot_id: _Aim(bearing, None) for mount in ship.weapons
                }
                title = f"Weapons at bearing {bearing:g}° rel"
                context = self._weapon_selection_context(bearing)
            else:
                contact = contacts[int(choice.removeprefix("contact:"))]
                aims = self._contact_aims(ship, contact)
                title = f"Weapons on {contact.display_name}"
                context = (
                    f"{BEARING_HINT} Each weapon aims at its own lead bearing, "
                    "assuming the target holds course and speed. "
                    "Toggle weapons, then finish this target."
                )

            selected = self._select_salvo_weapons(
                ship, aims=aims, used_slots=used_slots, title=title, context=context
            )
            if selected is None:
                continue
            for slot in selected:
                aim_bearing = aims[slot].bearing
                assert aim_bearing is not None
                shot: dict[str, int | float | str] = {"slot": slot, "bearing": aim_bearing}
                target_id = aims[slot].target_id
                if target_id is not None:
                    shot["target"] = target_id
                shots.append(shot)
                used_slots.add(slot)

    def _select_salvo_weapons(
        self,
        ship: Ship,
        *,
        aims: dict[int, _Aim],
        used_slots: set[int],
        title: str,
        context: str,
    ) -> list[int] | None:
        selected: set[int] = set()
        while True:
            reasons = {
                mount.slot_id: self._fire_unavailable_reason(
                    ship, mount.slot_id, aim=aims[mount.slot_id], used_slots=used_slots
                )
                for mount in ship.weapons
            }
            eligible = [mount.slot_id for mount in ship.weapons if reasons[mount.slot_id] is None]
            options = [
                MenuOption(
                    f"slot:{mount.slot_id}",
                    f"{'[x]' if mount.slot_id in selected else '[ ]'} {mount.display_name}",
                    self._aim_details(ship, mount, aims[mount.slot_id]),
                    disabled_reason=reasons[mount.slot_id],
                )
                for mount in ship.weapons
            ]
            options.extend(
                (
                    MenuOption(
                        "all",
                        "Add all eligible",
                        disabled_reason=(
                            None
                            if any(slot not in selected for slot in eligible)
                            else "No more eligible weapons."
                        ),
                    ),
                    MenuOption(
                        "done",
                        "Done with this target",
                        disabled_reason=None if selected else "Select at least one weapon.",
                    ),
                    MenuOption("back", "Back to target selection"),
                )
            )
            choice = self.ui.choose(title, options, context=context)
            if choice in {None, "back"}:
                return None
            if choice == "all":
                selected.update(eligible)
            elif choice == "done":
                return [mount.slot_id for mount in ship.weapons if mount.slot_id in selected]
            else:
                assert choice is not None
                slot = int(choice.removeprefix("slot:"))
                if slot in selected:
                    selected.remove(slot)
                else:
                    selected.add(slot)

    def _aim_details(self, ship: Ship, mount: WeaponMount, aim: _Aim) -> str:
        base = f"{arc_name(mount.arc)}; {arc_range_str(mount.arc)}; range {mount.weapon.range:g} GU"
        if aim.bearing is None or aim.distance is None:
            return base
        text = f"{base}\nAim {aim.bearing:.1f}° rel at {aim.distance:.0f} GU"
        if mount.weapon.speed > 0:
            spread = bearing_spread(ship, mount, self.session.state, aim.lock)
            chance = hit_probability(spread, aim.distance)
            text += f"; spread ±{spread:.1f}°; ~{chance:.0%} on target if it holds course"
        return text

    def _fire_unavailable_reason(
        self, ship: Ship, slot: int, *, aim: _Aim, used_slots: set[int]
    ) -> str | None:
        blocker = self._fire_blocker(ship, slot, aim=aim, used_slots=used_slots)
        return None if blocker is None else blocker[1]

    def _fire_blocker(
        self, ship: Ship, slot: int, *, aim: _Aim, used_slots: set[int]
    ) -> tuple[str, str] | None:
        """Return ``(kind, message)`` explaining why *slot* cannot fire, or None."""
        if slot in used_slots:
            return "queued", "Already queued in this salvo."
        mount = next(mount for mount in ship.weapons if mount.slot_id == slot)
        if not mount.can_fire:
            if mount.cooldown > 0:
                return "cooldown", f"Unavailable: cooldown for {mount.cooldown} more turn(s)."
            return "damaged", "Unavailable: weapon disabled by damage."
        if aim.bearing is None:
            return "out of range", (
                f"Unavailable: no intercept within range {mount.weapon.range:g} GU."
            )
        validated = validate_command(
            {
                "ship_id": ship.id,
                "action": "fire",
                "args": {"slot": slot, "bearing": aim.bearing},
            },
            ship,
            self.session.player_id,
            self.session.state.owner_lookup(),
        )
        if isinstance(validated, str):
            kind = "out of arc" if "outside" in validated else "invalid"
            return kind, f"Unavailable: {validated}"
        if aim.distance is not None and aim.distance > mount.weapon.range:
            return "out of range", (
                f"Unavailable: target at {aim.distance:.0f} GU exceeds "
                f"range {mount.weapon.range:g} GU."
            )
        return None

    def _contact_aims(self, ship: Ship, contact: ContactInfo) -> dict[int, _Aim]:
        """Per-weapon aim on *contact*: lead bearing for projectiles, direct for lances.

        BLIPs expose no course data, so they only get a direct bearing.
        """
        if not contact.targetable:
            bearing = self._relative_to(ship, contact.display_position)
            reach = distance(ship.position, contact.display_position)
            return {mount.slot_id: _Aim(bearing, reach) for mount in ship.weapons}
        aims: dict[int, _Aim] = {}
        for mount in ship.weapons:
            solution = aim_for(ship, mount, contact.ship, contact.display_position)
            if solution is not None:
                aims[mount.slot_id] = _Aim(
                    round(relative_bearing_360(ship.heading, solution.bearing), 2) % 360.0,
                    solution.intercept_distance,
                    contact.ship.id,
                    contact.detection_level,
                )
            else:
                aims[mount.slot_id] = _Aim(None, None)
        return aims

    def _contact_blockers(
        self, ship: Ship, contact: ContactInfo, used_slots: set[int]
    ) -> dict[int, tuple[str, str] | None]:
        aims = self._contact_aims(ship, contact)
        return {
            mount.slot_id: self._fire_blocker(
                ship, mount.slot_id, aim=aims[mount.slot_id], used_slots=used_slots
            )
            for mount in ship.weapons
        }

    @staticmethod
    def _blocker_summary(blockers: dict[int, tuple[str, str] | None]) -> str:
        counts: dict[str, int] = {}
        for blocker in blockers.values():
            if blocker is not None:
                counts[blocker[0]] = counts.get(blocker[0], 0) + 1
        return ", ".join(f"{count} {kind}" for kind, count in counts.items())

    def _fire_contact_option(
        self, index: int, ship: Ship, contact: ContactInfo, used_slots: set[int]
    ) -> MenuOption:
        details = self._fire_contact_details(ship, contact, used_slots)
        if not contact.targetable:
            return MenuOption(
                f"contact:{index}",
                contact.display_name,
                details,
                disabled_reason="BLIP: use manual bearing.",
            )
        blockers = self._contact_blockers(ship, contact, used_slots)
        ready = sum(1 for blocker in blockers.values() if blocker is None)
        if ready == 0:
            return MenuOption(
                f"contact:{index}",
                f"{contact.display_name} — no firing solution",
                details,
                disabled_reason=f"No weapon can fire: {self._blocker_summary(blockers)}.",
            )
        return MenuOption(
            f"contact:{index}",
            f"{contact.display_name} — {ready}/{len(blockers)} weapon(s) ready",
            details,
        )

    def _attack_summary(self, ship: Ship) -> str:
        contacts = [
            contact
            for contact in self.renderer.preview_contacts(
                ship, self.session.state, self.session.player_id
            )
            if not contact.is_friendly and contact.targetable
        ]
        if not contacts:
            return "No hostile on sensors: only blind manual-bearing fire."
        solutions = []
        for contact in contacts:
            blockers = self._contact_blockers(ship, contact, set())
            ready = sum(1 for blocker in blockers.values() if blocker is None)
            if ready:
                solutions.append(f"{contact.display_name} ({ready} weapon(s))")
        if not solutions:
            return "No firing solution: hostiles out of arc or range. Maneuver first."
        return "Firing solution on: " + ", ".join(solutions) + "."

    def _validated_fire_salvo(
        self, ship: Ship, shots: list[dict[str, int | float | str]]
    ) -> Command | None:
        validated = validate_command(
            {"ship_id": ship.id, "action": "fire", "args": {"shots": shots}},
            ship,
            self.session.player_id,
            self.session.state.owner_lookup(),
        )
        if isinstance(validated, str):
            self.ui.show(f"Invalid: {validated}")
            return None
        return validated

    def _fire_context(
        self,
        ship: Ship,
        contacts: list[ContactInfo],
        shots: list[dict[str, int | float | str]],
    ) -> str:
        lines = [BEARING_HINT]
        if not contacts:
            lines.append("No hostile contacts on sensors. Manual bearing fires blind.")
        for contact in contacts:
            bearing = self._relative_to(ship, contact.display_position)
            contact_distance = distance(ship.position, contact.display_position)
            approximate = "~" if contact.detection_level is DetectionLevel.BLIP else ""
            lines.append(
                f"{contact.display_name}: bearing {approximate}{bearing:.0f}° rel, "
                f"distance {approximate}{contact_distance:.0f} GU"
            )
        if shots:
            lines.append(self._format_shots(ship, shots))
        return "\n".join(lines)

    def _fire_contact_details(self, ship: Ship, contact: ContactInfo, used_slots: set[int]) -> str:
        bearing = self._relative_to(ship, contact.display_position)
        contact_distance = distance(ship.position, contact.display_position)
        approximate = "~" if contact.detection_level is DetectionLevel.BLIP else ""
        lines = [
            f"Bearing {approximate}{bearing:.0f}° rel; "
            f"distance {approximate}{contact_distance:.0f} GU"
        ]
        aims = self._contact_aims(ship, contact)
        for mount in ship.weapons:
            aim = aims[mount.slot_id]
            reason = self._fire_unavailable_reason(
                ship, mount.slot_id, aim=aim, used_slots=used_slots
            )
            if reason is not None:
                status = reason
            elif mount.weapon.speed > 0 and aim.distance is not None:
                spread = bearing_spread(ship, mount, self.session.state, aim.lock)
                chance = hit_probability(spread, aim.distance)
                eta = aim.distance / mount.weapon.speed
                status = (
                    f"READY — lead {aim.bearing:.0f}° rel, impact ~{eta:.1f} turn, "
                    f"~{chance:.0%} on target if it holds course"
                )
            else:
                status = "READY — instant hit"
            lines.append(f"{mount.display_name}: {status}")
        return "\n".join(lines)

    def _manual_fire_context(self, ship: Ship, used_slots: set[int]) -> str:
        lines = [f"{ship.name}: {BEARING_HINT}"]
        for mount in ship.weapons:
            queued = "; already queued" if mount.slot_id in used_slots else ""
            lines.append(
                f"{mount.display_name}: {arc_name(mount.arc)}, {arc_range_str(mount.arc)}, "
                f"range {mount.weapon.range:g} GU{queued}."
            )
        return "\n".join(lines)

    @staticmethod
    def _weapon_selection_context(bearing: float) -> str:
        return (
            f"Bearing {bearing:g}° rel. {BEARING_HINT} "
            "Manual bearing: no lead; range checked when fire resolves. "
            "Toggle weapons, then finish this bearing."
        )

    @staticmethod
    def _relative_to(ship: Ship, position: Vector2D) -> float:
        return relative_bearing_360(ship.heading, bearing_from_to(ship.position, position))

    @staticmethod
    def _format_shots(ship: Ship, shots: list[dict[str, int | float | str]]) -> str:
        lines = ["Queued salvo:"]
        for shot in shots:
            slot = int(shot["slot"])
            mount = next(mount for mount in ship.weapons if mount.slot_id == slot)
            lines.append(f"  {mount.display_name} → bearing {float(shot['bearing']):g}° rel")
        return "\n".join(lines)

    def _boarding_menu(self, ship: Ship) -> Command | None:
        while True:
            target = self.ui.choose(
                "Boarding target",
                tuple(
                    MenuOption(ci.ship.id, ci.display_name, self._contact_details(ship, ci))
                    for ci in self._hostile_contacts(ship)
                ),
            )
            if target is None:
                return None
            subsystem = self.ui.choose(
                "Target subsystem",
                tuple(
                    MenuOption(value, value.title())
                    for value in ("generator", "deck", "engines", "weapons")
                ),
                columns=2,
            )
            if subsystem is None:
                continue
            command = self._validated_command(ship, ["strike", target, subsystem])
            if command is not None:
                return command

    def _move_menu(self, ship: Ship) -> Command | None:
        while True:
            choice = self.ui.choose(
                f"Move — {ship.name}",
                (
                    MenuOption("ahead", "Ahead"),
                    MenuOption("stop", "Stop"),
                    MenuOption("turn", "Turn"),
                    MenuOption("back", "Back"),
                ),
                columns=2,
            )
            if choice in {None, "back"}:
                return None
            if choice == "stop":
                return self._validated_command(ship, ["stop"])
            if choice == "ahead":
                speed = self.ui.text(
                    "Speed (GU/turn)", "battle.move.speed", default=f"{ship.speed_max:g}"
                )
                if speed is None:
                    continue
                command = self._validated_command(ship, ["ahead", speed])
            else:
                while True:
                    direction = self.ui.choose(
                        "Turn direction",
                        (
                            MenuOption("port", "Port"),
                            MenuOption("starboard", "Starboard"),
                        ),
                        columns=2,
                    )
                    if direction is None:
                        command = None
                        break
                    degrees = self.ui.text("Turn angle (degrees)", "battle.move.angle")
                    if degrees is None:
                        continue
                    command = self._validated_command(ship, ["turn", direction, degrees])
                    if command is not None:
                        break
            if command is not None:
                return command

    def _tactic_menu(self, ship: Ship, pending: _PendingTurn) -> None:
        while True:
            choice = self.ui.choose(
                f"Tactic — {ship.name}",
                (
                    MenuOption("stance", "Stance"),
                    MenuOption("status", "Status"),
                    MenuOption("scan", "Scan"),
                    MenuOption("weapons", "Weapons"),
                    MenuOption("back", "Back"),
                ),
                columns=2,
            )
            if choice in {None, "back"}:
                return
            if choice in {"status", "scan", "weapons"}:
                self.ui.show(
                    self.renderer.preview_query(
                        self.session.player_id, ship, choice, self.session.state
                    )
                )
                continue
            stance = self.ui.choose(
                "Choose stance",
                tuple(
                    MenuOption(
                        item.value,
                        item.value.replace("_", " ").title(),
                        disabled_reason=self._stance_rejection(ship, item),
                    )
                    for item in Stance
                ),
            )
            if stance is not None:
                selected = Stance(stance)
                rejection = self._stance_rejection(ship, selected)
                if rejection is None:
                    pending.stances[ship.id] = selected
                else:
                    self.ui.show(f"Invalid stance: {rejection}")

    @staticmethod
    def _stance_rejection(ship: Ship, stance: Stance) -> str | None:
        if stance is ship.stance:
            return None
        if ship.stance_cooldown_remaining > 0:
            return f"Locked for {ship.stance_cooldown_remaining} more turn(s)."
        if not ship.subsystems.deck:
            return "Deck subsystem is damaged."
        if ship.morale <= 0:
            return "Crew has mutinied."
        return None

    def _validated_command(self, ship: Ship, tokens: list[str]) -> Command | None:
        raw = parse_action_command(ship.id, tokens)
        if isinstance(raw, str):
            self.ui.show(f"Invalid: {raw}")
            return None
        validated = validate_command(
            cast("dict[str, Any]", raw),
            ship,
            self.session.player_id,
            self.session.state.owner_lookup(),
        )
        if isinstance(validated, str):
            self.ui.show(f"Invalid: {validated}")
            return None
        return validated

    def _collect_ability(self) -> AbilityOrder | BattleOutcome | None:
        state = self.session.state
        fleet = state.fleets[self.session.player_id]
        self._scanner_ship = fleet.flagship_in(state)
        commander = fleet.commander
        if commander is None:
            return None
        while True:
            options = [MenuOption("ability:none", "None")]
            for ability_id in commander.active_ability_ids:
                definition = SkillRegistry.get_active(ability_id)
                if definition is None:
                    continue
                runtime = commander.ability_state.get(ability_id)
                charges = runtime.remaining_charges if runtime else definition.charges
                cooldown = runtime.cooldown_remaining if runtime else 0
                disabled = None
                if charges <= 0:
                    disabled = "No charges remaining."
                elif max(0, cooldown - 1) > 0:
                    disabled = f"Cooldown: {cooldown - 1} turn(s)."
                options.append(
                    MenuOption(
                        f"ability:{ability_id}",
                        definition.name,
                        f"Charges {charges}; cooldown {cooldown}",
                        disabled,
                    )
                )
            choice = self.ui.choose("Commander ability", options)
            if choice is None:
                continue
            if choice == "ability:none":
                return None
            order = self._ability_order(choice.removeprefix("ability:"))
            if order is None:
                continue
            rejection = validate_ability_order(
                state, fleet, commander, order, cooldown_will_tick=True
            )
            if rejection is not None:
                self.ui.show(f"Invalid ability: {rejection}")
                continue
            return order

    def _ability_order(self, ability_id: str) -> AbilityOrder | None:
        definition = SkillRegistry.get_active(ability_id)
        if definition is None:
            return None
        ship_target = any(
            isinstance(step, (ConcentratedFireBuff, BonusBoardingAssault))
            for step in definition.steps
        )
        position_target = any(
            isinstance(step, (Teleport, AreaHullDamage, AreaMoraleDamage, SpawnProbe))
            for step in definition.steps
        )
        target_id: str | None = None
        target_position: Vector2D | None = None
        if ship_target:
            flagship = self.session.state.fleets[self.session.player_id].flagship_in(
                self.session.state
            )
            if flagship is None:
                return None
            targets = [
                MenuOption(ci.ship.id, ci.display_name, self._contact_details(flagship, ci))
                for ci in self._hostile_contacts(flagship)
            ]
            if any(isinstance(step, ConcentratedFireBuff) for step in definition.steps):
                targets.extend(
                    MenuOption(ship_id, self.session.state.ships[ship_id].name, "Friendly ship")
                    for ship_id in self._alive_player_ids()
                )
            target_id = self.ui.choose(f"Target — {definition.name}", targets)
            if target_id is None:
                return None
        if position_target:
            x_raw = self.ui.text("Target X", "battle.ability.x")
            if x_raw is None:
                return None
            y_raw = self.ui.text("Target Y", "battle.ability.y")
            if y_raw is None:
                return None
            try:
                x, y = float(x_raw), float(y_raw)
            except ValueError:
                self.ui.show("Invalid ability: coordinates must be numbers.")
                return None
            if not math.isfinite(x) or not math.isfinite(y):
                self.ui.show("Invalid ability: coordinates must be finite.")
                return None
            target_position = Vector2D(x, y)
        return AbilityOrder(
            fleet_id=self.session.player_id,
            ability_id=ability_id,
            target_ship_id=target_id,
            target_position=target_position,
        )

    def _review(self, pending: _PendingTurn) -> bool | BattleOutcome:
        self._scanner_ship = self.session.state.fleets[self.session.player_id].flagship_in(
            self.session.state
        )
        while True:
            options = [
                MenuOption("confirm", "Confirm and resolve"),
                MenuOption("revise", "Revise whole turn"),
            ]
            options.extend(
                (
                    MenuOption("surrender", "Surrender"),
                    MenuOption("exit", "Leave battle"),
                )
            )
            choice = self.ui.choose(
                "Review turn",
                options,
                context=self._format_pending(pending),
                columns=2,
            )
            if choice is None:
                continue
            if choice == "confirm":
                return True
            if choice == "revise":
                return False
            if choice == "surrender":
                if self.ui.confirm("Surrender this battle?"):
                    return BattleOutcome.SURRENDER
                continue
            if choice == "exit":
                if self.ui.confirm("Leave this battle without resolving the turn?"):
                    return self._abandon()
                continue

    def _format_pending(self, pending: _PendingTurn) -> str:
        lines = ["Pending turn:"]
        for ship_id in self.session.state.player_ships[self.session.player_id]:
            command = pending.commands.get(ship_id)
            if command is None:
                continue
            ship = self.session.state.ships[ship_id]
            text = self._format_command(ship, command)
            stance = pending.stances.get(ship_id)
            if stance is not None:
                text += f"; stance {stance.value.replace('_', ' ').title()}"
            lines.append(f"  {ship.name}: {text}")
        if pending.ability is None:
            lines.append("  Commander ability: None")
        else:
            definition = SkillRegistry.get_active(pending.ability.ability_id)
            name = definition.name if definition else pending.ability.ability_id
            suffix = ""
            if pending.ability.target_ship_id is not None:
                suffix = f" → {self._target_name(pending.ability.target_ship_id)}"
            elif pending.ability.target_position is not None:
                suffix = f" at {pending.ability.target_position}"
            lines.append(f"  Commander ability: {name}{suffix}")
        return "\n".join(lines)

    def _format_command(self, ship: Ship, command: Command) -> str:
        if command.action == "pass":
            return "Wait"
        if command.action == "stop":
            return "Stop"
        if command.action == "ahead":
            return f"Ahead at {float(command.args['speed']):g} GU/turn"
        if command.action == "turn":
            return f"Turn {command.args['direction']} {float(command.args['degrees']):g}°"
        if command.action == "strike":
            return (
                f"Board {self._target_name(str(command.args['target']))}; "
                f"target {command.args['subsystem']}"
            )
        if "shots" in command.args:
            shots = cast("list[dict[str, int | float | str]]", command.args["shots"])
            return self._format_shots(ship, shots)
        slot = int(command.args["slot"])
        mount = next(item for item in ship.weapons if item.slot_id == slot)
        return (
            f"Fire {mount.weapon.name} ({mount.slot_name}) at bearing "
            f"{float(command.args['bearing']):g}° rel"
        )

    def _target_name(self, target_id: str) -> str:
        if target_id in self.session.state.player_ships[self.session.player_id]:
            return self.session.state.ships[target_id].name
        flagship = self.session.state.fleets[self.session.player_id].flagship_in(self.session.state)
        if flagship is not None:
            for contact in self.renderer.preview_contacts(
                flagship, self.session.state, self.session.player_id
            ):
                if (
                    contact.ship.id == target_id
                    and contact.detection_level is not DetectionLevel.BLIP
                ):
                    return contact.display_name
        return "Contact"

    def _hostile_contacts(self, observer: Ship) -> list[ContactInfo]:
        return [
            contact
            for contact in self.renderer.preview_contacts(
                observer, self.session.state, self.session.player_id
            )
            if not contact.is_friendly
            and contact.targetable
            and contact.detection_level is not DetectionLevel.BLIP
        ]

    @staticmethod
    def _contact_details(ship: Ship, contact: ContactInfo) -> str:
        bearing = relative_bearing_360(ship.heading, contact.true_bearing)
        return f"Bearing {bearing:.0f}° rel; distance {contact.true_distance:.1f} GU"

    def _alive_player_ids(self) -> list[str]:
        state = self.session.state
        return [
            ship_id
            for ship_id in state.player_ships[self.session.player_id]
            if state.ships[ship_id].alive
        ]

    def _render_turn(self, log: TurnLog) -> None:
        state = self.session.state
        self.ui.show(self.renderer.render_turn_result(self.session.player_id, log, state))
        for event in log.events:
            if isinstance(event, AbilityUsedEvent):
                self.ui.show(f"Ability used: {self._ability_name(event.ability_id)}.")
            elif isinstance(event, AbilityRejectedEvent):
                self.ui.show(
                    f"Ability {self._ability_name(event.ability_id)} rejected: {event.reason}."
                )
            elif isinstance(event, AbilityPrepStartedEvent):
                self.ui.show(
                    f"Ability {self._ability_name(event.ability_id)} preparing for "
                    f"{event.turns} turn(s)."
                )
            elif isinstance(event, AbilityInterruptedEvent):
                self.ui.show(
                    f"Ability {self._ability_name(event.ability_id)} interrupted: {event.reason}."
                )

    @staticmethod
    def _ability_name(ability_id: str) -> str:
        definition = SkillRegistry.get_active(ability_id)
        return definition.name if definition is not None else ability_id

    def _terminal_outcome(self) -> BattleOutcome | None:
        state = self.session.state
        player_alive = any(
            state.ships[ship_id].alive for ship_id in state.player_ships[self.session.player_id]
        )
        enemy_alive = any(state.ships[ship_id].alive for ship_id in self.session.enemy_runtime_ids)
        if not player_alive:
            return BattleOutcome.DEFEAT
        if not enemy_alive:
            return BattleOutcome.VICTORY
        return None

    def _abandon(self) -> BattleOutcome:
        self.ui.show("Battle abandoned. Continue returns to the previous campaign interval.")
        return BattleOutcome.ABANDONED
