"""Ship runtime state — hull + loadout + mutable battle state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.core.types import (
    Arc,
    Faction,
    MoraleState,
    Stance,
    Vector2D,
    heading_to_vector,
    normalize_angle,
)

if TYPE_CHECKING:
    from spacefleet.models.ship_profile import HullProfile
    from spacefleet.models.weapon import WeaponMount


@dataclass
class Ship:
    """A ship on the battlefield with full runtime state.

    Created from a *HullProfile* plus a weapon loadout.  Carries all mutable
    state: position, heading, speed, damage, shields, fires, morale.
    """

    # ── identity ──
    id: str
    name: str
    hull: HullProfile
    faction: Faction

    # ── spatial ──
    position: Vector2D
    heading: float  # degrees, 0 = north (+Y), clockwise
    speed: float  # current GU per turn

    # ── structure (mutable) ──
    hull_current: int
    shields_current: int

    # ── weapons ──
    weapons: list[WeaponMount] = field(default_factory=list)

    # ── status ──
    morale: int = 100
    morale_max: int = 100
    is_destroyed: bool = False
    fires: int = 0  # active fires (1 hull damage per fire per end-phase)

    # ── stance ──
    stance: Stance = Stance.STANDARD
    stance_cooldown_remaining: int = 0  # turns until next switch allowed

    # ── combustion gauge ──
    combustion: int = 100
    combustion_max: int = 100

    # ── subsystem stubs (True = operational) ──
    subsystem_generator: bool = True
    subsystem_deck: bool = True
    subsystem_engines: bool = True
    subsystem_weapons: bool = True

    # ── critical hit state ──
    crit_speed_modifier: float = 1.0  # 0.5 if engines damaged
    crit_thrusters_damaged: bool = False  # prevents turning
    crit_shields_suppressed_turns: int = 0  # turns until shields can regen
    crit_leadership_penalty: int = 0  # cumulative from bridge hits
    crit_temporary_repairs: list = field(default_factory=list)  # type: ignore[type-arg]

    # ── pending manoeuvre ──
    pending_turn: float = 0.0  # degrees remaining; positive = starboard, negative = port

    # ================================================================
    # Derived properties
    # ================================================================

    @property
    def hull_max(self) -> int:
        return self.hull.hull_hits

    @property
    def shields_max(self) -> int:
        return self.hull.shields

    @property
    def speed_max(self) -> float:
        return self.hull.speed

    @property
    def turn_rate(self) -> float:
        return self.hull.turn_rate

    @property
    def alive(self) -> bool:
        return not self.is_destroyed and self.hull_current > 0

    @property
    def turrets(self) -> int:
        return self.hull.turrets

    @property
    def effective_speed_max(self) -> float:
        """Speed max accounting for engine crits."""
        return self.hull.speed * self.crit_speed_modifier

    @property
    def effective_turn_rate(self) -> float:
        """Turn rate — 0 if thrusters damaged."""
        return 0.0 if self.crit_thrusters_damaged else self.hull.turn_rate

    @property
    def effective_leadership(self) -> int:
        """Leadership accounting for bridge crits."""
        return max(1, self.hull.leadership - self.crit_leadership_penalty)

    # ================================================================
    # Armor helpers
    # ================================================================

    def armor_for_arc(self, arc: Arc) -> int:
        """Armor value on a specific structural facing."""
        return {
            Arc.PROW: self.hull.armor_prow,
            Arc.PORT: self.hull.armor_port,
            Arc.STARBOARD: self.hull.armor_starboard,
            Arc.AFT: self.hull.armor_stern,
            # Dorsal hits use the weaker of port/starboard
            Arc.DORSAL: min(self.hull.armor_port, self.hull.armor_starboard),
        }.get(arc, self.hull.armor_port)

    def armor_for_bearing(self, relative_bearing: float) -> int:
        """Armor on the face struck by incoming fire.

        *relative_bearing* is the angle from this ship's heading to the
        incoming fire direction, in (−180, 180].
        Positive = fire hitting starboard side, negative = hitting port.
        """
        abs_rb = abs(relative_bearing)
        if abs_rb <= 45:
            return self.hull.armor_prow
        if abs_rb <= 135:
            return self.hull.armor_starboard if relative_bearing > 0 else self.hull.armor_port
        return self.hull.armor_stern

    def facing_arc_for_bearing(self, relative_bearing: float) -> Arc:
        """Which structural facing is hit by incoming fire."""
        abs_rb = abs(relative_bearing)
        if abs_rb <= 45:
            return Arc.PROW
        if abs_rb <= 135:
            return Arc.STARBOARD if relative_bearing > 0 else Arc.PORT
        return Arc.AFT

    # ================================================================
    # Stance
    # ================================================================

    def switch_stance(self, new_stance: Stance) -> bool:
        """Switch to *new_stance* if allowed.  Returns True on success."""
        if new_stance == self.stance:
            return True  # no-op always allowed
        if self.stance_cooldown_remaining > 0:
            return False
        if not self.subsystem_deck:
            return False  # deck critical blocks switching
        if self.morale <= 0:
            return False  # mutiny blocks switching
        from spacefleet.data.stance_registry import StanceRegistry

        self.stance = new_stance
        data = StanceRegistry.get_for(new_stance)
        self.stance_cooldown_remaining = data.switch_cooldown
        return True

    def tick_stance_cooldown(self) -> None:
        """Decrement stance cooldown by 1 (call once per end-of-turn)."""
        if self.stance_cooldown_remaining > 0:
            self.stance_cooldown_remaining -= 1

    # ================================================================
    # Morale
    # ================================================================

    def morale_state(self) -> MoraleState:
        """Current morale threshold bracket."""
        from spacefleet.models.morale import morale_state as _ms
        return _ms(self.morale)

    def apply_morale_change(self, delta: int) -> int:
        """Adjust morale clamped to [0, morale_max].  Returns actual change."""
        before = self.morale
        self.morale = max(0, min(self.morale_max, self.morale + delta))
        return self.morale - before

    # ================================================================
    # Combustion
    # ================================================================

    def regenerate_combustion(self, amount: int = 15) -> int:
        """Regen combustion gauge.  Returns actual gain."""
        before = self.combustion
        self.combustion = min(self.combustion_max, self.combustion + amount)
        return self.combustion - before

    # ================================================================
    # Damage
    # ================================================================

    def absorb_shields(self, hits: int) -> int:
        """Block hits with shields.  Returns hits that pass through."""
        blocked = min(hits, self.shields_current)
        self.shields_current -= blocked
        return hits - blocked

    def take_hull_damage(self, amount: int) -> None:
        """Apply raw hull damage.  Destroys ship at 0 hull."""
        self.hull_current = max(0, self.hull_current - amount)
        if self.hull_current <= 0:
            self.is_destroyed = True

    # ================================================================
    # Movement
    # ================================================================

    # Pivot rate multiplier when stationary (120 % — faster than under way,
    # but the ship is a sitting duck).
    PIVOT_RATE_MULTIPLIER: float = 1.2

    def apply_drift(self, fraction: float = 0.5) -> tuple[float, float]:
        """Move the ship along its heading by ``speed × fraction`` GU.

        If there is a *pending_turn* the heading rotates gradually during the
        drift, producing a curved arc (when moving) or a pivot in place (when
        stationary).

        Returns ``(heading_before, heading_after)`` for display purposes.
        """
        heading_before = self.heading

        if self.pending_turn != 0.0 and self.speed <= 0:
            # ── pivot in place (no position change) ──
            max_pivot = self.effective_turn_rate * fraction * self.PIVOT_RATE_MULTIPLIER
            sign = 1.0 if self.pending_turn > 0 else -1.0
            actual = sign * min(abs(self.pending_turn), max_pivot)
            self.heading = normalize_angle(self.heading + actual)
            self.pending_turn -= actual
            if abs(self.pending_turn) < 0.01:
                self.pending_turn = 0.0
            return (heading_before, self.heading)

        if self.speed <= 0:
            return (heading_before, self.heading)

        total_distance = self.speed * fraction

        if self.pending_turn != 0.0:
            # ── curved drift ──
            max_turn = self.effective_turn_rate * fraction
            sign = 1.0 if self.pending_turn > 0 else -1.0
            actual_turn = sign * min(abs(self.pending_turn), max_turn)

            # Simulate arc with micro-steps
            steps = 20
            turn_per_step = actual_turn / steps
            dist_per_step = total_distance / steps

            for _ in range(steps):
                self.heading = normalize_angle(self.heading + turn_per_step)
                direction = heading_to_vector(self.heading)
                self.position = self.position + direction * dist_per_step

            self.pending_turn -= actual_turn
            if abs(self.pending_turn) < 0.01:
                self.pending_turn = 0.0
        else:
            # ── straight-line drift ──
            direction = heading_to_vector(self.heading)
            self.position = self.position + direction * total_distance

        return (heading_before, self.heading)

    def apply_turn(self, degrees: float) -> None:
        """Set a pending turn order (positive = starboard, negative = port).

        The turn executes gradually during subsequent :meth:`apply_drift`
        calls at ``turn_rate`` degrees per turn.  A new order **replaces**
        any prior pending turn.  The full requested angle is stored and
        resolved over as many turns as needed.
        """
        self.pending_turn = degrees

    def set_speed(self, target: float) -> None:
        """Instantly change speed (clamped to [0, effective_speed_max])."""
        self.speed = max(0.0, min(self.effective_speed_max, target))

    # ================================================================
    # End-of-turn
    # ================================================================

    def regenerate_shields(self, amount: int = 1) -> int:
        """Regenerate shields.  Returns shields actually gained.

        Blocked when shields are suppressed (crit) or generator is damaged.
        """
        if self.crit_shields_suppressed_turns > 0:
            return 0
        if not self.subsystem_generator:
            return 0
        before = self.shields_current
        self.shields_current = min(self.shields_max, self.shields_current + amount)
        return self.shields_current - before

    def apply_fire_damage(self) -> int:
        """Each active fire deals 1 hull damage.  Returns damage dealt."""
        if self.fires <= 0:
            return 0
        dmg = self.fires
        self.take_hull_damage(dmg)
        return dmg

    # ================================================================
    # Critical hit ticking
    # ================================================================

    def tick_shields_suppressed(self) -> None:
        """Decrement shields suppressed counter (call once per end-of-turn)."""
        if self.crit_shields_suppressed_turns > 0:
            self.crit_shields_suppressed_turns -= 1

    def tick_temporary_repairs(self) -> None:
        """Tick down temporary boarding crits and reverse effects on expiry."""
        remaining: list[tuple[str, int]] = []
        for effect_key, turns_left in self.crit_temporary_repairs:
            new_turns = turns_left - 1
            if new_turns <= 0:
                self._reverse_temporary_crit(effect_key)
            else:
                remaining.append((effect_key, new_turns))
        self.crit_temporary_repairs = remaining

    def _reverse_temporary_crit(self, effect_key: str) -> None:
        """Restore a subsystem when its temporary crit expires."""
        if effect_key == "generator":
            self.subsystem_generator = True
        elif effect_key == "deck":
            self.subsystem_deck = True
        elif effect_key == "engines":
            self.subsystem_engines = True
            self.crit_speed_modifier = 1.0
        elif effect_key == "weapons":
            self.subsystem_weapons = True
        elif effect_key == "thrusters":
            self.crit_thrusters_damaged = False
        elif effect_key == "bridge":
            self.crit_leadership_penalty = max(
                0, self.crit_leadership_penalty - 3,
            )
        elif effect_key.startswith("weapon_"):
            slot_id = int(effect_key.split("_", 1)[1])
            for w in self.weapons:
                if w.slot_id == slot_id:
                    w.can_fire = True
                    break
        elif effect_key == "prow_weapons":
            for w in self.weapons:
                if w.arc == Arc.PROW:
                    w.can_fire = True

    # ================================================================
    # Factories
    # ================================================================

    @classmethod
    def from_profile(
        cls,
        ship_id: str,
        name: str,
        hull: HullProfile,
        weapons: list[WeaponMount],
        *,
        position: Vector2D | None = None,
        heading: float = 0.0,
        speed: float = 0.0,
    ) -> Ship:
        """Create a combat-ready ship from a hull profile + weapon loadout."""
        return cls(
            id=ship_id,
            name=name,
            hull=hull,
            faction=hull.faction,
            position=position or Vector2D(0.0, 0.0),
            heading=heading,
            speed=speed,
            hull_current=hull.hull_hits,
            shields_current=hull.shields,
            weapons=list(weapons),
            morale=hull.base_morale,
            morale_max=hull.base_morale,
        )

    def __repr__(self) -> str:
        turn_str = f", turn={self.pending_turn:+.0f}°" if self.pending_turn else ""
        return (
            f"Ship({self.name!r}, hull={self.hull_current}/{self.hull_max},"
            f" pos={self.position}, hdg={self.heading:.0f}°,"
            f" spd={self.speed:.0f}{turn_str})"
        )
