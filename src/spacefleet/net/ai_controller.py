"""AI controller — generates commands for AI-controlled ships.

A greedy per-ship fleet pilot: each controlled ship manages its stance,
picks the nearest enemy (preferring one already exposed by downed shields
when a firing solution exists), fires the best bearing weapon when it can,
and in the same turn turns to face or accelerates to close.  One
``Command`` (action plus maneuver) per ship per turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.combat.fire_control import aim_for
from spacefleet.core.types import Stance
from spacefleet.net.commands import Command, Maneuver
from spacefleet.spatial.geometry import (
    bearing_from_to,
    distance,
    is_in_arc,
    relative_bearing,
    relative_bearing_360,
)

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount
    from spacefleet.net.game_state import GameState

# Engage at ~60% of the ship's best weapon range.
ENGAGE_RANGE_FRACTION = 0.6
# Half-angle of the fixed "target is ahead" prow cone used for maneuvering.
PROW_CONE_DEGREES = 45.0
# Brace when hull drops below this fraction of max.
BRACE_HULL_FRACTION = 0.4


class AIController:
    """Greedy fleet pilot.  One command per alive controlled ship per turn."""

    def __init__(self, fire_chance: float = 1.0) -> None:
        self.fire_chance = fire_chance

    def generate_commands(
        self,
        state: GameState,
        controlled_ids: list[str] | None = None,
    ) -> dict[str, Command]:
        ids = controlled_ids if controlled_ids is not None else state.ai_ships
        commands: dict[str, Command] = {}
        for ship_id in ids:
            ship = state.ships.get(ship_id)
            if ship is None or not ship.alive:
                continue
            commands[ship_id] = self._decide(ship, state)
        return commands

    def _decide(self, ship: Ship, state: GameState) -> Command:
        if not ship.weapons:
            return Command(ship_id=ship.id, action="pass")
        enemies = [e for e in state.enemy_ships_of(ship) if e.alive]
        if not enemies:
            return Command(ship_id=ship.id, action="pass")
        target = self._choose_target(ship, enemies)
        self._manage_stance(ship, target)
        maneuver = self._maneuver(ship, target)

        solution = self._firing_solution(ship, target)
        if solution is not None and (
            self.fire_chance >= 1.0 or state.dice.chance(self.fire_chance)
        ):
            weapon, bearing = solution
            return Command(
                ship_id=ship.id,
                action="fire",
                args={"slot": weapon.slot_id, "bearing": bearing, "target": target.id},
                maneuver=maneuver,
            )
        return Command(ship_id=ship.id, action="pass", maneuver=maneuver)

    def _choose_target(self, ship: Ship, enemies: list[Ship]) -> Ship:
        """Nearest alive enemy; among those in a firing solution, prefer
        a shields-down target.  Deterministic tie-break by id."""
        in_solution = [e for e in enemies if self._firing_solution(ship, e) is not None]
        exposed = [e for e in in_solution if e.shields_current == 0]
        pool = exposed or in_solution or enemies
        return min(pool, key=lambda e: (distance(ship.position, e.position), e.id))

    def _firing_solution(self, ship: Ship, target: Ship) -> tuple[WeaponMount, float] | None:
        """Best (highest-strength) weapon whose aim point on *target* is
        in-arc and in-range, with its prow-relative (lead) bearing, or None."""
        candidates: list[tuple[WeaponMount, float]] = []
        for w in ship.weapons:
            if not w.can_fire:
                continue
            aim = aim_for(ship, w, target, target.position)
            if aim is not None and is_in_arc(ship.heading, aim.bearing, w.arc):
                candidates.append((w, relative_bearing_360(ship.heading, aim.bearing)))
        if not candidates:
            return None
        return max(candidates, key=lambda c: c[0].weapon.strength)

    def _maneuver(self, ship: Ship, target: Ship) -> Maneuver:
        bearing = bearing_from_to(ship.position, target.position)
        best_range = max(w.weapon.range for w in ship.weapons)
        # Decide "is the target roughly ahead?" by a fixed ±45° PROW cone around
        # the ship's heading, independent of weapon arcs — broadside ships must
        # still turn toward the enemy to close, even though their guns bear.
        rel = relative_bearing(ship.heading, bearing)  # + = starboard, - = port
        ahead = abs(rel) <= PROW_CONE_DEGREES

        if not ahead:
            # Turn at the current speed, up to what the ship can manage this turn.
            degrees = min(abs(rel), ship.max_turn_this_turn(ship.speed))
            if degrees <= 0.0:
                return Maneuver(speed=0.0)
            return Maneuver(turn=degrees if rel > 0 else -degrees)

        dist = distance(ship.position, target.position)
        if dist > best_range * ENGAGE_RANGE_FRACTION:
            return Maneuver(speed=ship.effective_speed_max)

        return Maneuver(speed=0.0)

    def _manage_stance(self, ship: Ship, target: Ship) -> None:
        if ship.stance_cooldown_remaining > 0:
            return
        crippled = ship.hull_current < BRACE_HULL_FRACTION * ship.hull.hull_hits
        if crippled:
            if ship.stance != Stance.BRACE_FOR_IMPACT:
                ship.switch_stance(Stance.BRACE_FOR_IMPACT)
            return
        best_range = max(w.weapon.range for w in ship.weapons)
        in_range = distance(ship.position, target.position) <= best_range
        if in_range and ship.stance != Stance.LOCK_ON:
            ship.switch_stance(Stance.LOCK_ON)
