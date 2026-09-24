"""Persistent records for the single-player campaign."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.commander.commander import Commander
    from spacefleet.core.types import Faction
    from spacefleet.models.fleet_spec import ShipSpec


class CampaignStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    DEFEATED = "defeated"


class BattleOutcome(StrEnum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    SURRENDER = "surrender"
    TURN_LIMIT = "turn_limit"
    ABANDONED = "abandoned"


@dataclass
class CampaignShip:
    id: str
    spec: ShipSpec
    hull_damage: int = 0
    battles_survived: int = 0


@dataclass
class CampaignState:
    fleet_name: str
    seed: int
    encounter: int
    status: CampaignStatus
    credits: int
    next_ship_id: int
    faction: Faction
    roster: list[CampaignShip]
    flagship_id: str | None
    commander: Commander
    last_resolved_battle_id: str | None = None
