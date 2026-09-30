"""Campaign interval operations as detached, previewable candidates (no UI).

Every change is computed on a deep copy of the campaign ("candidate"); the
screen shows the preview, asks for confirmation, then adopts the candidate
and autosaves.  Unaffordable options are still quoted — with the charge they
would cost — so the UI can list them disabled with a reason.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.campaign.economy import (
    REPAIR_COST_PER_HULL,
    CampaignEconomyError,
    buy_ship,
    reequip_ship,
    repair_all,
    repair_ship,
)
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.models.fleet_spec import ShipSpec, ship_points
from spacefleet.persistence.campaign_save import CampaignSaveError, save_campaign

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from spacefleet.campaign.battle import BattleReport
    from spacefleet.campaign.models import CampaignShip, CampaignState
    from spacefleet.models.ship_profile import HullProfile


@dataclass(frozen=True)
class Quote:
    """A priced candidate.  ``candidate`` is None when ``reason`` blocks it."""

    candidate: CampaignState | None
    charge: int  # credits taken (negative: refund)
    balance: int  # credits after the change
    reason: str | None = None

    @property
    def preview(self) -> str:
        return f"{credit_change(self.charge)}; resulting credits {self.balance}"


@dataclass(frozen=True)
class HullOffer:
    hull: HullProfile
    quote: Quote


def autosave(campaign: CampaignState, path: Path) -> str | None:
    """Save *campaign*; return an error line for the log, or None on success."""
    try:
        save_campaign(campaign, path)
    except CampaignSaveError as exc:
        return f"Change kept in memory but UNSAVED: {exc}. Press w to retry."
    return None


def credit_change(charge: int) -> str:
    if charge > 0:
        return f"charge {charge} credits"
    if charge < 0:
        return f"refund {-charge} credits"
    return "no credit change"


def find_ship(campaign: CampaignState, ship_id: str) -> CampaignShip:
    for ship in campaign.roster:
        if ship.id == ship_id:
            return ship
    raise ValueError(f"unknown campaign ship {ship_id!r}")


def quote_refit(campaign: CampaignState, ship_id: str, replacement: ShipSpec) -> Quote:
    """Price replacing *ship_id*'s spec.  Raises CampaignEconomyError when illegal."""
    candidate = deepcopy(campaign)
    try:
        charge = reequip_ship(candidate, ship_id, replacement)
    except CampaignEconomyError as exc:
        if str(exc) != "insufficient credits":
            raise
        funded = deepcopy(campaign)
        funded.credits += ship_points(replacement)
        charge = reequip_ship(funded, ship_id, replacement)
        return Quote(None, charge, campaign.credits - charge, "insufficient credits")
    return Quote(candidate, charge, candidate.credits)


def refit_validator(campaign: CampaignState, ship_id: str) -> Callable[[ShipSpec], None]:
    """``fitting_choices`` candidate validator: legal regardless of credits."""

    def validate(replacement: ShipSpec) -> None:
        funded = deepcopy(campaign)
        funded.credits += ship_points(replacement)
        reequip_ship(funded, ship_id, replacement)

    return validate


def unique_ship_name(campaign: CampaignState, base: str) -> str:
    names = {ship.spec.name for ship in campaign.roster}
    name, suffix = base, 2
    while name in names:
        name = f"{base} {suffix}"
        suffix += 1
    return name


def quote_buy(campaign: CampaignState, spec: ShipSpec) -> Quote:
    """Price buying *spec*.  Raises CampaignEconomyError when illegal."""
    candidate = deepcopy(campaign)
    try:
        buy_ship(candidate, spec)
    except CampaignEconomyError as exc:
        if str(exc) != "insufficient credits":
            raise
        charge = ship_points(spec)
        funded = deepcopy(campaign)
        funded.credits += charge
        buy_ship(funded, spec)
        return Quote(None, charge, campaign.credits - charge, "insufficient credits")
    return Quote(candidate, campaign.credits - candidate.credits, candidate.credits)


def hull_offers(campaign: CampaignState) -> list[HullOffer]:
    """Every faction hull the campaign may buy, affordable or not."""
    offers = []
    for hull in HullRegistry.by_faction(campaign.faction):
        spec = ShipSpec(unique_ship_name(campaign, hull.name), hull.id)
        try:
            quote = quote_buy(campaign, spec)
        except CampaignEconomyError:
            continue
        offers.append(HullOffer(hull, quote))
    return offers


def _quote_repair(campaign: CampaignState, operation: Callable[[CampaignState], int]) -> Quote:
    candidate = deepcopy(campaign)
    try:
        charge = operation(candidate)
    except CampaignEconomyError as exc:
        if str(exc) != "insufficient credits":
            raise
        funded = deepcopy(campaign)
        funded.credits += sum(s.hull_damage for s in campaign.roster) * REPAIR_COST_PER_HULL
        charge = operation(funded)
        return Quote(None, charge, campaign.credits - charge, "insufficient credits")
    return Quote(candidate, charge, candidate.credits)


def quote_repair_all(campaign: CampaignState) -> Quote:
    return _quote_repair(campaign, repair_all)


def quote_repair_ship(campaign: CampaignState, ship_id: str) -> Quote:
    return _quote_repair(campaign, lambda state: repair_ship(state, ship_id))


def battle_result_line(report: BattleReport, ship_names: dict[str, str]) -> str:
    """One log line summarising a closed battle."""
    casualties = ", ".join(f"{ship_id} ({ship_names[ship_id]})" for ship_id in report.casualties)
    return (
        f"Battle {report.outcome.value.replace('_', ' ')}: "
        f"{report.enemy_destroyed} enemies destroyed, {report.player_survivors} survivors, "
        f"credits awarded {report.credits_awarded}, "
        f"casualties: {casualties or '(none)'}."
    )
