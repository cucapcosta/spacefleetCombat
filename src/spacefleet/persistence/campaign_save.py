"""Versioned, atomic JSON persistence for single-player campaigns."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from spacefleet.campaign.models import CampaignShip, CampaignState, CampaignStatus
from spacefleet.campaign.rules import validate_campaign_state
from spacefleet.commander.commander import Commander
from spacefleet.core.types import Faction
from spacefleet.models.fleet_spec import ShipSpec

CAMPAIGN_SAVE_VERSION = 1

_CAMPAIGN_FIELDS = frozenset(
    {
        "version",
        "fleet_name",
        "seed",
        "encounter",
        "status",
        "credits",
        "next_ship_id",
        "faction",
        "roster",
        "flagship_id",
        "commander",
        "last_resolved_battle_id",
    }
)
_SHIP_FIELDS = frozenset({"id", "spec", "hull_damage", "battles_survived"})
_SPEC_FIELDS = frozenset({"name", "hull_id", "weapons", "upgrade_ids", "doctrine_id"})
_COMMANDER_FIELDS = frozenset(
    {
        "id",
        "name",
        "faction",
        "level",
        "xp",
        "active_ability_ids",
        "passive_skill_ids",
        "trait_ids",
    }
)


class CampaignSaveError(ValueError):
    """Raised when campaign persistence cannot safely complete."""


def _object(value: object, context: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CampaignSaveError(f"{context} must be a JSON object")
    if not all(type(key) is str for key in value):
        raise CampaignSaveError(f"{context} field names must be strings")
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], context: str) -> None:
    missing = sorted(expected - value.keys())
    if missing:
        raise CampaignSaveError(f"{context} is missing field {missing[0]!r}")
    unexpected = sorted(value.keys() - expected)
    if unexpected:
        raise CampaignSaveError(f"{context} has unexpected field {unexpected[0]!r}")


def _string(value: object, context: str) -> str:
    if type(value) is not str:
        raise CampaignSaveError(f"{context} must be a string")
    return value


def _optional_string(value: object, context: str) -> str | None:
    if value is None:
        return None
    result = _string(value, context)
    if not result:
        raise CampaignSaveError(f"{context} must not be empty")
    return result


def _integer(value: object, context: str) -> int:
    if type(value) is not int:
        raise CampaignSaveError(f"{context} must be an integer")
    return value


def _list(value: object, context: str) -> list[Any]:
    if type(value) is not list:
        raise CampaignSaveError(f"{context} must be a list")
    return value


def _string_list(value: object, context: str) -> list[str]:
    items = _list(value, context)
    result: list[str] = []
    for index, item in enumerate(items):
        result.append(_string(item, f"{context}[{index}]"))
    return result


def _enum_value(
    enum_type: type[CampaignStatus] | type[Faction], value: object, context: str
) -> Any:
    raw = _string(value, context)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise CampaignSaveError(f"invalid {context} {raw!r}") from exc


def _ship_spec_from_dict(value: object, context: str) -> ShipSpec:
    data = _object(value, context)
    _exact_fields(data, _SPEC_FIELDS, context)
    weapon_data = _object(data["weapons"], f"{context}.weapons")
    weapons: dict[int, str] = {}
    for raw_slot, weapon_id in weapon_data.items():
        if not raw_slot.isdigit() or raw_slot == "0" or str(int(raw_slot)) != raw_slot:
            raise CampaignSaveError(f"{context} weapon slot {raw_slot!r} is invalid")
        weapons[int(raw_slot)] = _string(weapon_id, f"{context}.weapons[{raw_slot!r}]")
    doctrine_id = data["doctrine_id"]
    if doctrine_id is not None:
        doctrine_id = _string(doctrine_id, f"{context}.doctrine_id")
    return ShipSpec(
        name=_string(data["name"], f"{context}.name"),
        hull_id=_string(data["hull_id"], f"{context}.hull_id"),
        weapons=weapons,
        upgrade_ids=_string_list(data["upgrade_ids"], f"{context}.upgrade_ids"),
        doctrine_id=doctrine_id,
    )


def _campaign_ship_from_dict(value: object, index: int) -> CampaignShip:
    context = f"roster[{index}]"
    data = _object(value, context)
    _exact_fields(data, _SHIP_FIELDS, context)
    return CampaignShip(
        id=_string(data["id"], f"{context}.id"),
        spec=_ship_spec_from_dict(data["spec"], f"{context}.spec"),
        hull_damage=_integer(data["hull_damage"], f"{context}.hull_damage"),
        battles_survived=_integer(data["battles_survived"], f"{context}.battles_survived"),
    )


def _commander_from_dict(value: object) -> Commander:
    data = _object(value, "commander")
    _exact_fields(data, _COMMANDER_FIELDS, "commander")
    return Commander(
        id=_string(data["id"], "commander.id"),
        name=_string(data["name"], "commander.name"),
        faction=_enum_value(Faction, data["faction"], "commander.faction"),
        level=_integer(data["level"], "commander.level"),
        xp=_integer(data["xp"], "commander.xp"),
        active_ability_ids=_string_list(data["active_ability_ids"], "commander.active_ability_ids"),
        passive_skill_ids=_string_list(data["passive_skill_ids"], "commander.passive_skill_ids"),
        trait_ids=_string_list(data["trait_ids"], "commander.trait_ids"),
    )


def campaign_from_dict(value: object) -> CampaignState:
    """Strictly decode and validate a version-1 campaign object."""
    data = _object(value, "campaign save")
    version = _integer(data.get("version"), "version")
    if version != CAMPAIGN_SAVE_VERSION:
        raise CampaignSaveError(f"unsupported campaign save version {version}")
    _exact_fields(data, _CAMPAIGN_FIELDS, "campaign save")

    roster_data = _list(data["roster"], "roster")
    campaign = CampaignState(
        fleet_name=_string(data["fleet_name"], "fleet_name"),
        seed=_integer(data["seed"], "seed"),
        encounter=_integer(data["encounter"], "encounter"),
        status=_enum_value(CampaignStatus, data["status"], "status"),
        credits=_integer(data["credits"], "credits"),
        next_ship_id=_integer(data["next_ship_id"], "next_ship_id"),
        faction=_enum_value(Faction, data["faction"], "faction"),
        roster=[_campaign_ship_from_dict(item, index) for index, item in enumerate(roster_data)],
        flagship_id=_optional_string(data["flagship_id"], "flagship_id"),
        commander=_commander_from_dict(data["commander"]),
        last_resolved_battle_id=_optional_string(
            data["last_resolved_battle_id"], "last_resolved_battle_id"
        ),
    )
    try:
        validate_campaign_state(campaign)
    except (KeyError, ValueError) as exc:
        raise CampaignSaveError(f"invalid campaign state: {exc}") from exc
    return campaign


def _ship_spec_to_dict(spec: ShipSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "hull_id": spec.hull_id,
        "weapons": {str(slot_id): weapon_id for slot_id, weapon_id in spec.weapons.items()},
        "upgrade_ids": list(spec.upgrade_ids),
        "doctrine_id": spec.doctrine_id,
    }


def campaign_to_dict(campaign: CampaignState) -> dict[str, Any]:
    """Encode durable campaign state, excluding commander battle runtime."""
    try:
        validate_campaign_state(campaign)
        data: dict[str, Any] = {
            "version": CAMPAIGN_SAVE_VERSION,
            "fleet_name": campaign.fleet_name,
            "seed": campaign.seed,
            "encounter": campaign.encounter,
            "status": campaign.status.value,
            "credits": campaign.credits,
            "next_ship_id": campaign.next_ship_id,
            "faction": campaign.faction.value,
            "roster": [
                {
                    "id": ship.id,
                    "spec": _ship_spec_to_dict(ship.spec),
                    "hull_damage": ship.hull_damage,
                    "battles_survived": ship.battles_survived,
                }
                for ship in campaign.roster
            ],
            "flagship_id": campaign.flagship_id,
            "commander": {
                "id": campaign.commander.id,
                "name": campaign.commander.name,
                "faction": campaign.commander.faction.value,
                "level": campaign.commander.level,
                "xp": campaign.commander.xp,
                "active_ability_ids": list(campaign.commander.active_ability_ids),
                "passive_skill_ids": list(campaign.commander.passive_skill_ids),
                "trait_ids": list(campaign.commander.trait_ids),
            },
            "last_resolved_battle_id": campaign.last_resolved_battle_id,
        }
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CampaignSaveError):
            raise
        raise CampaignSaveError(f"invalid campaign state: {exc}") from exc
    campaign_from_dict(data)
    return data


def save_campaign(campaign: CampaignState, path: Path) -> Path:
    """Atomically write a validated campaign to *path*."""
    try:
        encoded = (
            json.dumps(campaign_to_dict(campaign), indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    except (AttributeError, TypeError, ValueError) as exc:
        if isinstance(exc, CampaignSaveError):
            raise
        raise CampaignSaveError(f"could not encode campaign: {exc}") from exc

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except OSError as exc:
        raise CampaignSaveError(f"could not save campaign to {path}: {exc}") from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        with suppress(OSError):
            Path(temp_name).unlink(missing_ok=True)
        raise CampaignSaveError(f"could not save campaign to {path}: {exc}") from exc
    return path


def load_campaign(path: Path) -> CampaignState:
    """Load and strictly validate a campaign save file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CampaignSaveError(f"could not load campaign from {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CampaignSaveError(
            f"could not load campaign from {path}: invalid JSON: {exc}"
        ) from exc
    try:
        return campaign_from_dict(data)
    except CampaignSaveError as exc:
        raise CampaignSaveError(f"could not load campaign from {path}: {exc}") from exc


def default_campaign_path() -> Path:
    """Return the default save location in the current directory."""
    return Path.cwd() / "campaign-save.json"
