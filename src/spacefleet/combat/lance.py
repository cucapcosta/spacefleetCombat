"""Lance resolution helpers — 1D6 per strength, 4+ hits, ignores armor."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

LANCE_HIT_THRESHOLD = 4


def lance_hit_count(rolls: Iterable[int]) -> int:
    """Number of dice in *rolls* that meet the lance hit threshold."""
    return sum(1 for r in rolls if r >= LANCE_HIT_THRESHOLD)
