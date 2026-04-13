"""Tests for the stance state helpers."""

from __future__ import annotations

from spacefleet.core.types import Stance
from spacefleet.models.stance import StanceState, can_switch


def test_can_switch_when_no_cooldown():
    state = StanceState(stance=Stance.STANDARD)
    assert can_switch(state, deck_operational=True, morale=100) is True


def test_cannot_switch_with_cooldown():
    state = StanceState(stance=Stance.LOCK_ON, cooldown_remaining=1)
    assert can_switch(state, deck_operational=True, morale=100) is False


def test_cannot_switch_without_deck():
    state = StanceState(stance=Stance.STANDARD)
    assert can_switch(state, deck_operational=False, morale=100) is False


def test_cannot_switch_in_mutiny():
    state = StanceState(stance=Stance.STANDARD)
    assert can_switch(state, deck_operational=True, morale=0) is False


def test_tick_decrements_cooldown():
    state = StanceState(stance=Stance.LOCK_ON, cooldown_remaining=2)
    state.tick()
    assert state.cooldown_remaining == 1
    state.tick()
    state.tick()
    assert state.cooldown_remaining == 0
