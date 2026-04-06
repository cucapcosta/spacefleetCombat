"""Hull profile registry — loads from ``data/ships/**/*.yaml``.

Falls back to the inline definitions in :mod:`demo_data` when YAML
loading is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from spacefleet.core.types import Arc, Faction, ShipClass, WeaponSize, WeaponType
from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_all_yaml_in_dir
from spacefleet.models.ship_profile import HullProfile, WeaponSlotDef

logger = logging.getLogger(__name__)

# sensor_range is not stored in the YAML files; derive from classification.
_SENSOR_RANGE_BY_CLASS: dict[ShipClass, float] = {
    ShipClass.ESCORT: 30.0,
    ShipClass.LIGHT_CRUISER: 40.0,
    ShipClass.CRUISER: 50.0,
    ShipClass.BATTLECRUISER: 60.0,
    ShipClass.BATTLESHIP: 70.0,
}


def _parse_weapon_slot(raw: dict[str, Any]) -> WeaponSlotDef:
    return WeaponSlotDef(
        id=int(raw["id"]),
        name=raw["name"],
        arc=Arc(raw["arc"]),
        size=WeaponSize(raw["size"]),
        allowed_types=tuple(WeaponType(t) for t in raw["allowed_types"]),
    )


def _parse_hull(raw: dict[str, Any]) -> HullProfile | None:
    """Convert a raw YAML dict (one ship file) into a :class:`HullProfile`."""
    try:
        classification = ShipClass(raw["classification"])
        hull = raw["hull"]
        movement = raw["movement"]
        boarding = raw.get("boarding") or {}
        morale = raw.get("morale") or {}

        weapon_slots = tuple(_parse_weapon_slot(slot) for slot in raw.get("weapon_slots", []))

        return HullProfile(
            id=raw["id"],
            name=raw["name"],
            classification=classification,
            faction=Faction(raw["faction"]),
            hull_cost=int(raw["hull_cost"]),
            leadership=int(raw["leadership"]),
            hull_hits=int(hull["hits"]),
            armor_prow=int(hull["armor_prow"]),
            armor_port=int(hull["armor_port"]),
            armor_starboard=int(hull["armor_starboard"]),
            armor_stern=int(hull["armor_stern"]),
            speed=float(movement["speed"]),
            turn_rate=float(movement["turn_rate"]),
            shields=int(raw["shields"]),
            turrets=int(raw["turrets"]),
            sensor_range=_SENSOR_RANGE_BY_CLASS.get(classification, 40.0),
            weapon_slots=weapon_slots,
            assault_actions=int(boarding.get("assault_actions", 0)),
            base_morale=int(morale.get("base_max", 100)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        ship_id = raw.get("id", "<unknown>")
        logger.warning("Failed to parse hull '%s': %s", ship_id, exc)
        return None


class HullRegistry:
    """Singleton-style registry for hull profiles."""

    _hulls: dict[str, HullProfile] = {}
    _loaded: bool = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True

        if not YAML_AVAILABLE:
            logger.info("PyYAML unavailable — hull registry uses demo fallback")
            cls._load_demo_fallback()
            return

        data_dir = get_data_dir()
        if data_dir is None:
            logger.warning("Data directory not found — using demo fallback")
            cls._load_demo_fallback()
            return

        ships_dir = data_dir / "ships"
        raw_list = load_all_yaml_in_dir(ships_dir, recursive=True)

        for raw in raw_list:
            profile = _parse_hull(raw)
            if profile is not None:
                cls._hulls[profile.id] = profile

        logger.info("Loaded %d hull profiles from YAML", len(cls._hulls))

        if not cls._hulls:
            logger.warning("No hulls loaded — using demo fallback")
            cls._load_demo_fallback()

    @classmethod
    def _load_demo_fallback(cls) -> None:
        from spacefleet.data.demo_data import DAUNTLESS_HULL, HULK_HULL

        for hull in (DAUNTLESS_HULL, HULK_HULL):
            cls._hulls[hull.id] = hull

    @classmethod
    def get(cls, hull_id: str) -> HullProfile:
        """Look up a hull by ID.  Raises :exc:`KeyError` if not found."""
        cls._load()
        return cls._hulls[hull_id]

    @classmethod
    def get_or_none(cls, hull_id: str) -> HullProfile | None:
        cls._load()
        return cls._hulls.get(hull_id)

    @classmethod
    def all(cls) -> dict[str, HullProfile]:
        cls._load()
        return dict(cls._hulls)

    @classmethod
    def by_faction(cls, faction: Faction) -> list[HullProfile]:
        cls._load()
        return [h for h in cls._hulls.values() if h.faction == faction]

    @classmethod
    def by_class(cls, ship_class: ShipClass) -> list[HullProfile]:
        cls._load()
        return [h for h in cls._hulls.values() if h.classification == ship_class]

    @classmethod
    def reset(cls) -> None:
        """Clear the registry (for testing)."""
        cls._hulls.clear()
        cls._loaded = False
