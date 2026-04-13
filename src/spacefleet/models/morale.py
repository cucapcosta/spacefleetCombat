"""Pure helpers for morale brackets, accuracy factor and speed caps.

The Ship class delegates state-bracket lookups to these helpers so
combat code can call them without holding a Ship reference.
"""
from __future__ import annotations

from spacefleet.core.types import MoraleState


def morale_state(morale: int) -> MoraleState:
    """Return the bracket for a morale value in [0, 100]."""
    if morale >= 75:
        return MoraleState.FULL
    if morale >= 50:
        return MoraleState.SHAKEN
    if morale >= 25:
        return MoraleState.WAVERING
    if morale >= 1:
        return MoraleState.BREAKING
    return MoraleState.MUTINY


_ACCURACY: dict[MoraleState, float] = {
    MoraleState.FULL: 1.0,
    MoraleState.SHAKEN: 0.9,
    MoraleState.WAVERING: 0.75,
    MoraleState.BREAKING: 0.5,
    MoraleState.MUTINY: 0.0,
}


def accuracy_factor(state: MoraleState) -> float:
    """Hit-count multiplier for ships at this morale bracket."""
    return _ACCURACY[state]


def speed_cap(state: MoraleState, max_speed: float) -> float:
    """Maximum speed permitted at this morale bracket.

    * FULL/SHAKEN: no penalty
    * WAVERING: ``max - 5`` GU
    * BREAKING: half speed
    * MUTINY: 0
    """
    if state in (MoraleState.FULL, MoraleState.SHAKEN):
        return max_speed
    if state == MoraleState.WAVERING:
        return max(0.0, max_speed - 5.0)
    if state == MoraleState.BREAKING:
        return max_speed * 0.5
    return 0.0
