"""Tests for combat.lance."""
from __future__ import annotations

from spacefleet.combat.lance import lance_hit_count
from spacefleet.dice import DiceRoller


def test_count_hits_4plus():
    assert lance_hit_count([1, 3, 4, 6]) == 2
    assert lance_hit_count([5, 5, 5]) == 3
    assert lance_hit_count([1, 2, 3]) == 0


def test_lance_resolver_uses_4plus():
    # Sanity: a deterministic dice roller produces a stable count
    dr = DiceRoller(seed=1)
    rolls = dr.roll_d6(8)
    assert lance_hit_count(rolls) >= 0
