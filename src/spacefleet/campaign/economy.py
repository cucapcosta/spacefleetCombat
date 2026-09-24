"""Atomic fleet purchases, refits, repairs, and roster edits."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import ship_points

from .models import CampaignShip, CampaignStatus
from .rules import validate_campaign_state

if TYPE_CHECKING:
    from spacefleet.campaign.models import CampaignState
    from spacefleet.models.fleet_spec import ShipSpec

REPAIR_COST_PER_HULL = 8


class CampaignEconomyError(ValueError):
    """Raised when a campaign economy operation cannot be completed."""


def _validate_editable(campaign: CampaignState) -> None:
    if campaign.status is not CampaignStatus.ACTIVE:
        raise CampaignEconomyError("campaign is not active")
    try:
        validate_campaign_state(campaign)
    except ValueError as exc:
        raise CampaignEconomyError(str(exc)) from exc


def _validate_candidate(candidate: CampaignState) -> None:
    try:
        validate_campaign_state(candidate)
    except ValueError as exc:
        raise CampaignEconomyError(str(exc)) from exc


def _ship_index(campaign: CampaignState, ship_id: str) -> int:
    for index, ship in enumerate(campaign.roster):
        if ship.id == ship_id:
            return index
    raise CampaignEconomyError(f"unknown campaign ship {ship_id!r}")


def _weapon_cost(weapon_id: str) -> int:
    weapon = WeaponRegistry.get_or_none(weapon_id)
    if weapon is None:
        raise CampaignEconomyError(f"unknown weapon id {weapon_id!r}")
    return weapon.cost


def _upgrade_cost(upgrade_id: str) -> int:
    upgrade = UpgradeRegistry.get_or_none(upgrade_id)
    if upgrade is None:
        raise CampaignEconomyError(f"unknown upgrade id {upgrade_id!r}")
    return upgrade.cost


def _doctrine_cost(doctrine_id: str) -> int:
    doctrine = DoctrineRegistry.get_or_none(doctrine_id)
    if doctrine is None:
        raise CampaignEconomyError(f"unknown doctrine id {doctrine_id!r}")
    return doctrine.cost


def _equipment_charge(current: ShipSpec, replacement: ShipSpec) -> int:
    charge = 0
    for slot_id in current.weapons.keys() | replacement.weapons.keys():
        old_weapon = current.weapons.get(slot_id)
        new_weapon = replacement.weapons.get(slot_id)
        if old_weapon == new_weapon:
            continue
        if old_weapon is not None:
            charge -= _weapon_cost(old_weapon) // 2
        if new_weapon is not None:
            charge += _weapon_cost(new_weapon)

    old_upgrades = set(current.upgrade_ids)
    new_upgrades = set(replacement.upgrade_ids)
    charge -= sum(_upgrade_cost(upgrade_id) // 2 for upgrade_id in old_upgrades - new_upgrades)
    charge += sum(_upgrade_cost(upgrade_id) for upgrade_id in new_upgrades - old_upgrades)

    if current.doctrine_id != replacement.doctrine_id:
        if current.doctrine_id is not None:
            charge -= _doctrine_cost(current.doctrine_id) // 2
        if replacement.doctrine_id is not None:
            charge += _doctrine_cost(replacement.doctrine_id)
    return charge


def buy_ship(campaign: CampaignState, spec: ShipSpec) -> str:
    """Buy a ship at full catalog cost and return its stable campaign ID."""
    _validate_editable(campaign)
    try:
        cost = ship_points(spec)
    except ValueError as exc:
        raise CampaignEconomyError(str(exc)) from exc
    if campaign.credits < cost:
        raise CampaignEconomyError("insufficient credits")

    ship_id = f"ship-{campaign.next_ship_id}"
    candidate = deepcopy(campaign)
    candidate.roster.append(CampaignShip(id=ship_id, spec=deepcopy(spec)))
    candidate.next_ship_id += 1
    candidate.credits -= cost
    _validate_candidate(candidate)

    campaign.roster.append(CampaignShip(id=ship_id, spec=deepcopy(spec)))
    campaign.next_ship_id += 1
    campaign.credits -= cost
    return ship_id


def reequip_ship(campaign: CampaignState, ship_id: str, replacement: ShipSpec) -> int:
    """Replace one ship's equipment and return its net credit charge."""
    _validate_editable(campaign)
    index = _ship_index(campaign, ship_id)
    saved = campaign.roster[index]
    if replacement.hull_id != saved.spec.hull_id:
        raise CampaignEconomyError("changing a campaign ship hull is not allowed")

    charge = _equipment_charge(saved.spec, replacement)
    if campaign.credits < charge:
        raise CampaignEconomyError("insufficient credits")

    candidate = deepcopy(campaign)
    candidate.roster[index].spec = deepcopy(replacement)
    candidate.credits -= charge
    _validate_candidate(candidate)

    saved.spec = deepcopy(replacement)
    campaign.credits -= charge
    return charge


def discard_ship(campaign: CampaignState, ship_id: str) -> None:
    """Discard a roster ship without issuing a refund."""
    _validate_editable(campaign)
    index = _ship_index(campaign, ship_id)
    candidate = deepcopy(campaign)
    candidate.roster.pop(index)
    if candidate.flagship_id == ship_id:
        candidate.flagship_id = None
    _validate_candidate(candidate)

    campaign.roster.pop(index)
    if campaign.flagship_id == ship_id:
        campaign.flagship_id = None


def repair_ship(campaign: CampaignState, ship_id: str) -> int:
    """Fully repair one ship and return the credits charged."""
    _validate_editable(campaign)
    index = _ship_index(campaign, ship_id)
    cost = campaign.roster[index].hull_damage * REPAIR_COST_PER_HULL
    if campaign.credits < cost:
        raise CampaignEconomyError("insufficient credits")

    candidate = deepcopy(campaign)
    candidate.roster[index].hull_damage = 0
    candidate.credits -= cost
    _validate_candidate(candidate)

    campaign.roster[index].hull_damage = 0
    campaign.credits -= cost
    return cost


def repair_all(campaign: CampaignState) -> int:
    """Fully repair the roster as one all-or-nothing purchase."""
    _validate_editable(campaign)
    total = sum(ship.hull_damage * REPAIR_COST_PER_HULL for ship in campaign.roster)
    if campaign.credits < total:
        raise CampaignEconomyError("insufficient credits")

    candidate = deepcopy(campaign)
    for ship in candidate.roster:
        ship.hull_damage = 0
    candidate.credits -= total
    _validate_candidate(candidate)

    for ship in campaign.roster:
        ship.hull_damage = 0
    campaign.credits -= total
    return total


def set_flagship(campaign: CampaignState, ship_id: str) -> None:
    """Designate a roster ship as flagship after revalidating the roster."""
    _validate_editable(campaign)
    _ship_index(campaign, ship_id)
    candidate = deepcopy(campaign)
    candidate.flagship_id = ship_id
    _validate_candidate(candidate)

    campaign.flagship_id = ship_id
