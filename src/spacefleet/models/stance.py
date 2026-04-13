"""Stance state container + pure switch-eligibility helpers."""

from __future__ import annotations

from dataclasses import dataclass

from spacefleet.core.types import Stance


@dataclass
class StanceState:
    """Mutable stance + cooldown carried by a ship."""

    stance: Stance = Stance.STANDARD
    cooldown_remaining: int = 0

    def tick(self) -> None:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1


def can_switch(
    state: StanceState,
    *,
    deck_operational: bool,
    morale: int,
) -> bool:
    """True when the ship is allowed to switch stance this turn."""
    if state.cooldown_remaining > 0:
        return False
    if not deck_operational:
        return False
    return morale > 0
