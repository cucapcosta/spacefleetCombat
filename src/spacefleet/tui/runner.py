"""Contract between the campaign flow and whatever runs a battle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from spacefleet.campaign.models import BattleOutcome


class BattleRunner(Protocol):
    def run(self) -> BattleOutcome: ...
