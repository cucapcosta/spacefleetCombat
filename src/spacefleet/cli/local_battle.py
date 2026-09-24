"""Synchronous local controller for campaign battles."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from spacefleet.campaign.models import BattleOutcome
from spacefleet.cli.action_parser import parse_action_command
from spacefleet.cli.game_cmd import format_commander_status, parse_ability_command
from spacefleet.commander.abilities import AbilityUsedEvent
from spacefleet.core.types import Stance
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

if TYPE_CHECKING:
    from collections.abc import Callable

    from spacefleet.campaign.battle import BattleSession
    from spacefleet.models.ship import Ship

_HELP = """\
Local battle commands:
  fire <weapon#> <bearing>       fire a weapon
  ahead [speed]                  set speed (full speed when omitted)
  stop                           set speed to zero
  turn <port|starboard> <deg>    queue a turn
  strike <target_id> <subsystem> attempt a lightning strike
  pass                           submit no ship action
  stance [name]                  queue a stance; stance alone lists choices
  status | scan | weapons        inspect without advancing
  ability <ability_id> [target_id] use one commander ability
  ability <ability_id> at <x> <y>
  ability skip                   submit no commander ability
  review | revise | confirm      inspect, discard, or resolve queued orders
  surrender | quit               end or abandon the battle

Use shown target IDs for strike and targeted abilities.
"""


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
    ) -> None:
        if turn_limit < 1:
            raise ValueError("turn limit must be positive")
        self.session = session
        self.input = input_fn
        self.output = output_fn
        self.renderer = renderer or ServerRenderer()
        self.ai = ai or AIController()
        self.turn_limit = turn_limit

    def run(self) -> BattleOutcome:
        """Run until victory, defeat, surrender, turn limit, or abandonment."""
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
                switched = self.session.state.ships[ship_id].switch_stance(stance)
                if not switched:
                    raise RuntimeError(f"queued stance for {ship_id!r} became invalid")

            state = self.session.state
            state.advance_turn()
            ai_commands = self.ai.generate_commands(
                state,
                controlled_ids=self.session.enemy_runtime_ids,
            )
            ability_orders = {self.session.player_id: pending.ability} if pending.ability else {}
            log = resolve_turn(
                state,
                pending.commands | ai_commands,
                ability_orders,
            )
            self._render_turn(log)

    def _collect_turn(self) -> _PendingTurn | BattleOutcome:
        pending = _PendingTurn()
        state = self.session.state
        player_id = self.session.player_id
        alive_ids = [
            ship_id for ship_id in state.player_ships[player_id] if state.ships[ship_id].alive
        ]
        owner_lookup = state.owner_lookup()

        for index, ship_id in enumerate(alive_ids, start=1):
            ship = state.ships[ship_id]
            while True:
                self.output(self.renderer.render_ship_brief(ship, state, player_id))
                self.output(f"  Ship ID: {ship.id}")
                prompt = self.renderer.render_prompt(
                    ship,
                    index,
                    len(alive_ids),
                    state,
                    player_id,
                )
                tokens = self._read_tokens(f"{prompt}\n  > ")
                if tokens == ["quit"]:
                    return self._abandon()
                if tokens == ["surrender"]:
                    return BattleOutcome.SURRENDER
                if not tokens:
                    self.output("Invalid: enter a command or type help.")
                    continue

                command = tokens[0].lower()
                if command in {"status", "scan", "weapons"} and len(tokens) == 1:
                    self.output(self.renderer.render_query(player_id, ship, command, state))
                    continue
                if command in {"help", "?"}:
                    self.output(_HELP)
                    continue
                if command == "stance":
                    error = self._queue_stance(ship, tokens[1:], pending)
                    if error is not None:
                        self.output(f"Invalid stance: {error}")
                    continue

                raw = parse_action_command(ship_id, tokens)
                if isinstance(raw, str):
                    self.output(f"Invalid: {raw}")
                    continue
                validated = validate_command(
                    cast("dict[str, Any]", raw),
                    ship,
                    player_id,
                    owner_lookup,
                )
                if isinstance(validated, str):
                    self.output(f"Invalid: {validated}")
                    continue
                pending.commands[ship_id] = validated
                break

        ability = self._collect_ability()
        if isinstance(ability, BattleOutcome):
            return ability
        pending.ability = ability
        return pending

    def _collect_ability(self) -> AbilityOrder | BattleOutcome | None:
        state = self.session.state
        fleet = state.fleets[self.session.player_id]
        commander = fleet.commander
        if commander is None:
            return None

        while True:
            self.output(format_commander_status(commander))
            tokens = self._read_tokens("  Commander ability (ability skip for none)> ")
            if tokens == ["quit"]:
                return self._abandon()
            if tokens == ["surrender"]:
                return BattleOutcome.SURRENDER
            if tokens and tokens[0].lower() in {"help", "?"}:
                self.output(_HELP)
                continue
            if tokens == ["ability", "skip"]:
                return None
            if not tokens or tokens[0].lower() != "ability":
                self.output("Invalid ability: use ability <ability_id> or ability skip.")
                continue
            order = parse_ability_command(tokens[1:], self.session.player_id)
            if order is None or (
                order.target_position is not None
                and not (
                    math.isfinite(order.target_position.x)
                    and math.isfinite(order.target_position.y)
                )
            ):
                self.output("Invalid ability syntax or non-finite target position.")
                continue
            rejection = validate_ability_order(
                state,
                fleet,
                commander,
                order,
                cooldown_will_tick=True,
            )
            if rejection is not None:
                self.output(f"Invalid ability: {rejection}")
                continue
            return order

    def _review(self, pending: _PendingTurn) -> bool | BattleOutcome:
        self.output(self._format_pending(pending))
        while True:
            tokens = self._read_tokens("  review | confirm | revise | surrender | quit > ")
            if tokens == ["confirm"]:
                return True
            if tokens == ["revise"]:
                return False
            if tokens == ["review"]:
                self.output(self._format_pending(pending))
                continue
            if tokens == ["surrender"]:
                return BattleOutcome.SURRENDER
            if tokens == ["quit"]:
                return self._abandon()
            if tokens and tokens[0].lower() in {"help", "?"}:
                self.output(_HELP)
                continue
            self.output("Invalid review choice. Use review, confirm, revise, surrender, or quit.")

    def _queue_stance(
        self,
        ship: Ship,
        args: list[str],
        pending: _PendingTurn,
    ) -> str | None:
        if not args:
            queued = pending.stances.get(ship.id)
            suffix = f"; queued {queued.value}" if queued is not None else ""
            valid = ", ".join(stance.value for stance in Stance)
            self.output(f"Current stance: {ship.stance.value}{suffix}. Available: {valid}")
            return None
        if len(args) != 1:
            return "use stance <name>"
        try:
            stance = Stance(args[0].lower())
        except ValueError:
            return f"unknown stance {args[0]!r}"
        if stance is not ship.stance:
            if ship.stance_cooldown_remaining > 0:
                return f"locked for {ship.stance_cooldown_remaining} more turn(s)"
            if not ship.subsystems.deck:
                return "deck subsystem is damaged"
            if ship.morale <= 0:
                return "crew has mutinied"
        pending.stances[ship.id] = stance
        self.output(f"Queued stance {stance.value} for {ship.name}.")
        return None

    def _format_pending(self, pending: _PendingTurn) -> str:
        lines = ["Pending turn:"]
        for ship_id in self.session.state.player_ships[self.session.player_id]:
            command = pending.commands.get(ship_id)
            if command is None:
                continue
            stance = pending.stances.get(ship_id)
            stance_text = f", stance={stance.value}" if stance is not None else ""
            lines.append(f"  {ship_id}: {command.action} {command.args}{stance_text}")
        if pending.ability is None:
            lines.append("  ability: none")
        else:
            lines.append(f"  ability: {pending.ability.ability_id}")
        return "\n".join(lines)

    def _render_turn(self, log: TurnLog) -> None:
        state = self.session.state
        self.output(self.renderer.render_turn_result(self.session.player_id, log, state))
        for event in log.events:
            if isinstance(event, AbilityUsedEvent):
                self.output(f"Ability used: {event.ability_id}.")
            elif isinstance(event, AbilityRejectedEvent):
                self.output(f"Ability {event.ability_id} rejected: {event.reason}.")
            elif isinstance(event, AbilityPrepStartedEvent):
                self.output(f"Ability {event.ability_id} preparing for {event.turns} turn(s).")
            elif isinstance(event, AbilityInterruptedEvent):
                self.output(f"Ability {event.ability_id} interrupted: {event.reason}.")

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

    def _read_tokens(self, prompt: str) -> list[str]:
        try:
            return self.input(prompt).strip().split()
        except (EOFError, KeyboardInterrupt):
            return ["quit"]

    def _abandon(self) -> BattleOutcome:
        self.output("Battle abandoned. Continue returns to the previous campaign interval.")
        return BattleOutcome.ABANDONED
