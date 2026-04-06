"""Dice roller for Spacefleet Combat.

Provides a global ``dice`` instance used by all game systems.
Replace it (or pass a seed) for deterministic testing.
"""

from __future__ import annotations

import random


class DiceRoller:
    """Injectable dice roller backed by a ``random.Random`` instance."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    # -- single-die rolls --

    def d6(self) -> int:
        return self._rng.randint(1, 6)

    def d3(self) -> int:
        return self._rng.randint(1, 3)

    # -- multi-die rolls --

    def roll_d6(self, count: int) -> list[int]:
        return [self.d6() for _ in range(count)]

    def roll_2d6(self) -> int:
        return self.d6() + self.d6()

    # -- utility --

    def chance(self, probability: float) -> bool:
        """Return *True* with the given probability (0.0 – 1.0)."""
        return self._rng.random() < probability

    def randint(self, low: int, high: int) -> int:
        return self._rng.randint(low, high)

    def uniform(self, low: float, high: float) -> float:
        return self._rng.uniform(low, high)


# Global dice roller – importable everywhere.
dice = DiceRoller()
