from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.campaign.rules import new_campaign
from spacefleet.core.types import Faction
from spacefleet.models.fleet_spec import FleetSpec, ShipSpec

if TYPE_CHECKING:
    from spacefleet.campaign.models import CampaignState


def supported_fleet(faction: Faction = Faction.IMPERIAL_NAVY) -> FleetSpec:
    if faction is Faction.IMPERIAL_NAVY:
        ships = [
            ShipSpec(
                "Test Flag",
                "dauntless_light_cruiser",
                {1: "macro_cannon_2", 2: "macro_cannon_2", 3: "lance_2"},
            ),
            ShipSpec(
                "Test Escort",
                "sword_frigate",
                {1: "macro_cannon_1", 2: "macro_cannon_1"},
            ),
        ]
    else:
        ships = [
            ShipSpec(
                "Test Flag",
                "slaughter_cruiser",
                {1: "macro_cannon_3", 2: "macro_cannon_3", 3: "lance_2"},
            ),
            ShipSpec(
                "Test Escort",
                "iconoclast_destroyer",
                {1: "macro_cannon_1", 2: "macro_cannon_1"},
            ),
        ]
    return FleetSpec(name="Test Fleet", faction=faction, ships=ships, flagship_index=0)


def campaign_state(faction: Faction = Faction.IMPERIAL_NAVY) -> CampaignState:
    return new_campaign(supported_fleet(faction), "Test Commander", seed=7)


class ScriptedIO:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)
        self.outputs: list[str] = []

    def input(self, _prompt: str) -> str:
        return next(self._lines)

    def output(self, text: str) -> None:
        self.outputs.append(text)
