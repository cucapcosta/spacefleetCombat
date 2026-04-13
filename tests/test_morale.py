"""Tests for the morale helpers."""

from __future__ import annotations

from spacefleet.core.types import MoraleState
from spacefleet.models.morale import (
    accuracy_factor,
    morale_state,
    speed_cap,
)


def test_state_buckets():
    assert morale_state(100) == MoraleState.FULL
    assert morale_state(75) == MoraleState.FULL
    assert morale_state(74) == MoraleState.SHAKEN
    assert morale_state(50) == MoraleState.SHAKEN
    assert morale_state(49) == MoraleState.WAVERING
    assert morale_state(25) == MoraleState.WAVERING
    assert morale_state(24) == MoraleState.BREAKING
    assert morale_state(1) == MoraleState.BREAKING
    assert morale_state(0) == MoraleState.MUTINY


def test_accuracy_factor_drops_with_morale():
    assert accuracy_factor(MoraleState.FULL) == 1.0
    assert accuracy_factor(MoraleState.SHAKEN) == 0.9
    assert accuracy_factor(MoraleState.WAVERING) == 0.75
    assert accuracy_factor(MoraleState.BREAKING) == 0.5
    assert accuracy_factor(MoraleState.MUTINY) == 0.0


def test_speed_cap_brackets():
    assert speed_cap(MoraleState.FULL, 20.0) == 20.0
    assert speed_cap(MoraleState.SHAKEN, 20.0) == 20.0
    assert speed_cap(MoraleState.WAVERING, 20.0) == 15.0
    assert speed_cap(MoraleState.BREAKING, 20.0) == 10.0
    assert speed_cap(MoraleState.MUTINY, 20.0) == 0.0
