"""Campaign fleet eligibility, persistent invariants, and enemy presets."""

from __future__ import annotations

import re
import secrets
from copy import deepcopy
from typing import TYPE_CHECKING

from spacefleet.commander.doctrine_effects import apply_doctrine_to_hull
from spacefleet.core.types import Faction, WeaponType
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    ShipSpec,
    apply_default_loadout,
    fleet_points,
    validate_fleet_spec,
    validate_ship_spec,
)
from spacefleet.net.game_state import build_starter_commander

from .models import CampaignShip, CampaignState, CampaignStatus

if TYPE_CHECKING:
    from spacefleet.commander.commander import Commander

SUPPORTED_WEAPON_TYPES = frozenset({WeaponType.BATTERY, WeaponType.LANCE})
INITIAL_CREDITS = 800
BLOCKED_UPGRADES = frozenset({"power_ram", "automated_reload"})
BLOCKED_ABILITIES = frozenset({"augur_probe", "torpedo_barrage"})
BLOCKED_PASSIVES = frozenset({"short_burn_torpedoes", "reload_drills"})

_SHIP_ID_PATTERN = re.compile(r"ship-([1-9][0-9]*)\Z")


def _validate_commander(commander: Commander, faction: Faction) -> None:
    if commander.faction is not faction:
        raise FleetSpecError("commander faction does not match fleet faction")
    if not commander.id or not commander.name:
        raise FleetSpecError("commander id and name must not be empty")
    if commander.level < 1:
        raise FleetSpecError("commander level must be positive")
    if commander.xp < 0:
        raise FleetSpecError("commander xp must not be negative")

    for ability_id in commander.active_ability_ids:
        ability = SkillRegistry.get_active(ability_id)
        if ability is None:
            raise FleetSpecError(f"unknown active ability id {ability_id!r}")
        if ability.faction is not None and ability.faction != faction.value:
            raise FleetSpecError(
                f"ability {ability_id!r} does not belong to faction {faction.value!r}"
            )
        if ability_id in BLOCKED_ABILITIES:
            raise FleetSpecError(f"ability {ability_id!r} is not supported in campaign")

    for passive_id in commander.passive_skill_ids:
        passive = SkillRegistry.get_passive(passive_id)
        if passive is None:
            raise FleetSpecError(f"unknown passive skill id {passive_id!r}")
        if passive.faction is not None and passive.faction != faction.value:
            raise FleetSpecError(
                f"passive {passive_id!r} does not belong to faction {faction.value!r}"
            )
        if passive_id in BLOCKED_PASSIVES:
            raise FleetSpecError(f"passive {passive_id!r} is not supported in campaign")

    for trait_id in commander.trait_ids:
        if SkillRegistry.get_trait(trait_id) is None:
            raise FleetSpecError(f"unknown trait id {trait_id!r}")
    if commander.trait_ids:
        raise FleetSpecError("commander traits are not supported in campaign")


def _validate_supported_ship(spec: ShipSpec) -> None:
    for weapon_id in spec.weapons.values():
        weapon = WeaponRegistry.get_or_none(weapon_id)
        if weapon is None:
            raise FleetSpecError(f"unknown weapon id {weapon_id!r}")
        if weapon.weapon_type not in SUPPORTED_WEAPON_TYPES:
            raise FleetSpecError(
                f"weapon {weapon_id!r} uses unsupported {weapon.weapon_type.value} mechanics"
            )
    for upgrade_id in spec.upgrade_ids:
        if upgrade_id in BLOCKED_UPGRADES:
            raise FleetSpecError(f"upgrade {upgrade_id!r} is not supported in campaign")


def validate_campaign_fleet(fleet: FleetSpec, commander: Commander | None = None) -> None:
    """Validate normal fleet rules, then the campaign's supported-content subset."""
    validate_fleet_spec(fleet)
    for spec in fleet.ships:
        _validate_supported_ship(spec)
    if commander is not None:
        _validate_commander(commander, fleet.faction)


def campaign_fleet_spec(campaign: CampaignState) -> FleetSpec:
    """Create a detached fleet spec from a persistent roster."""
    flagship_index = 0
    if campaign.flagship_id is not None:
        for index, ship in enumerate(campaign.roster):
            if ship.id == campaign.flagship_id:
                flagship_index = index
                break
    return FleetSpec(
        name=campaign.fleet_name,
        faction=campaign.faction,
        ships=[deepcopy(ship.spec) for ship in campaign.roster],
        flagship_index=flagship_index,
    )


def _ship_hull_max(spec: ShipSpec) -> int:
    hull = HullRegistry.get(spec.hull_id)
    if spec.doctrine_id is None:
        return hull.hull_hits
    doctrine = DoctrineRegistry.get(spec.doctrine_id)
    return apply_doctrine_to_hull(hull, doctrine).hull_hits


def validate_campaign_state(
    campaign: CampaignState,
    *,
    require_battle_ready: bool = False,
) -> None:
    """Validate persistent state, optionally requiring a fleet ready for combat."""
    if not campaign.fleet_name:
        raise FleetSpecError("fleet name must not be empty")
    if not isinstance(campaign.status, CampaignStatus):
        raise FleetSpecError("invalid campaign status")
    if campaign.seed < 0:
        raise FleetSpecError("campaign seed must not be negative")
    if not 1 <= campaign.encounter <= 5:
        raise FleetSpecError("campaign encounter must be between 1 and 5")
    if campaign.credits < 0:
        raise FleetSpecError("campaign credits must not be negative")
    if campaign.next_ship_id < 1:
        raise FleetSpecError("next ship id must be positive")
    _validate_commander(campaign.commander, campaign.faction)

    ids = [ship.id for ship in campaign.roster]
    if len(ids) != len(set(ids)):
        raise FleetSpecError("duplicate campaign ship id")
    names = [ship.spec.name for ship in campaign.roster]
    if len(names) != len(set(names)):
        raise FleetSpecError("duplicate ship name in campaign roster")

    highest_id = 0
    for ship in campaign.roster:
        match = _SHIP_ID_PATTERN.fullmatch(ship.id)
        if match is None:
            raise FleetSpecError(f"invalid campaign ship id {ship.id!r}")
        highest_id = max(highest_id, int(match.group(1)))
        is_flagship = ship.id == campaign.flagship_id
        validate_ship_spec(ship.spec, campaign.faction, is_flagship=is_flagship)
        _validate_supported_ship(ship.spec)
        if ship.hull_damage < 0:
            raise FleetSpecError("ship hull damage must not be negative")
        if ship.hull_damage >= _ship_hull_max(ship.spec):
            raise FleetSpecError(f"ship {ship.id!r} has lethal hull damage")
        if ship.battles_survived < 0:
            raise FleetSpecError("ship battles survived must not be negative")

    if campaign.next_ship_id <= highest_id:
        raise FleetSpecError("next ship id must be greater than all allocated ship ids")
    if campaign.flagship_id is not None and campaign.flagship_id not in ids:
        raise FleetSpecError("flagship id does not reference the campaign roster")

    if require_battle_ready:
        if campaign.status is not CampaignStatus.ACTIVE:
            raise FleetSpecError("battle-ready campaign must be active")
        if not campaign.roster:
            raise FleetSpecError("battle-ready campaign needs at least one ship")
        if campaign.flagship_id is None:
            raise FleetSpecError("battle-ready campaign needs a flagship")
        fleet = campaign_fleet_spec(campaign)
        validate_fleet_spec(fleet)
        validate_campaign_fleet(fleet, campaign.commander)


def new_campaign(fleet: FleetSpec, commander_name: str, seed: int | None) -> CampaignState:
    """Create the initial persistent campaign state from an eligible fleet."""
    validate_fleet_spec(fleet, budget=INITIAL_CREDITS)
    commander = build_starter_commander("player", fleet.faction)
    commander.name = commander_name
    validate_campaign_fleet(fleet, commander)
    roster = [
        CampaignShip(id=f"ship-{index}", spec=deepcopy(spec))
        for index, spec in enumerate(fleet.ships, start=1)
    ]
    campaign = CampaignState(
        seed=seed if seed is not None else secrets.randbits(63),
        fleet_name=fleet.name,
        encounter=1,
        status=CampaignStatus.ACTIVE,
        credits=INITIAL_CREDITS - fleet_points(fleet),
        next_ship_id=len(roster) + 1,
        faction=fleet.faction,
        roster=roster,
        flagship_id=roster[fleet.flagship_index].id,
        commander=commander,
    )
    validate_campaign_state(campaign, require_battle_ready=True)
    return campaign


_ENEMY_COMPOSITIONS: dict[Faction, tuple[tuple[str, ...], ...]] = {
    Faction.CHAOS_FLEET: (
        ("iconoclast_destroyer", "iconoclast_destroyer"),
        ("slaughter_cruiser", "iconoclast_destroyer", "iconoclast_destroyer"),
        ("murder_cruiser", "slaughter_cruiser"),
        ("desolator_battleship", "iconoclast_destroyer", "iconoclast_destroyer"),
        ("desolator_battleship", "murder_cruiser", "slaughter_cruiser"),
    ),
    Faction.IMPERIAL_NAVY: (
        ("sword_frigate", "sword_frigate"),
        ("dauntless_light_cruiser", "sword_frigate", "sword_frigate"),
        ("lunar_cruiser", "dauntless_light_cruiser"),
        ("emperor_battleship", "sword_frigate", "sword_frigate"),
        ("emperor_battleship", "lunar_cruiser", "dauntless_light_cruiser"),
    ),
}


def _supported_default_ship(hull_id: str, name: str) -> ShipSpec:
    spec = ShipSpec(name=name, hull_id=hull_id)
    apply_default_loadout(spec)
    spec.weapons = {
        slot_id: weapon_id
        for slot_id, weapon_id in spec.weapons.items()
        if WeaponRegistry.get(weapon_id).weapon_type in SUPPORTED_WEAPON_TYPES
    }
    spec.upgrade_ids = [
        upgrade_id for upgrade_id in spec.upgrade_ids if upgrade_id not in BLOCKED_UPGRADES
    ]
    return spec


def enemy_fleet_for(player_faction: Faction, encounter: int) -> FleetSpec:
    """Return the fixed supported enemy fleet for an encounter."""
    if not 1 <= encounter <= 5:
        raise ValueError(f"unknown campaign encounter {encounter}")
    enemy_faction = (
        Faction.CHAOS_FLEET if player_faction is Faction.IMPERIAL_NAVY else Faction.IMPERIAL_NAVY
    )
    hull_ids = _ENEMY_COMPOSITIONS[enemy_faction][encounter - 1]
    ships = [
        _supported_default_ship(hull_id, f"Enemy {encounter}-{index}")
        for index, hull_id in enumerate(hull_ids, start=1)
    ]
    fleet = FleetSpec(
        name=f"Encounter {encounter} {enemy_faction.value}",
        faction=enemy_faction,
        ships=ships,
        flagship_index=0,
    )
    validate_campaign_fleet(fleet)
    return fleet
