"""Weapon profile registry — loads from ``data/weapons/weapon_catalog.yaml``.

Falls back to the inline definitions in :mod:`demo_data` when YAML
loading is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from spacefleet.core.types import WeaponSize, WeaponType
from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_yaml_file
from spacefleet.models.weapon import WeaponProfile

logger = logging.getLogger(__name__)

# Default projectile speed by weapon type (when YAML omits ``speed``)
_DEFAULT_SPEED: dict[WeaponType, float] = {
    WeaponType.BATTERY: 60.0,
    WeaponType.LANCE: 0.0,
    WeaponType.TORPEDO: 30.0,
    WeaponType.NOVA_CANNON: 0.0,
}


def _parse_weapon(weapon_id: str, raw: dict[str, Any]) -> WeaponProfile | None:
    """Convert a raw YAML dict into a :class:`WeaponProfile`."""
    try:
        wtype = WeaponType(raw["type"])
        wsize = WeaponSize(raw["size"])

        special: dict[str, Any] = raw.get("special") or {}

        speed = float(raw.get("speed", _DEFAULT_SPEED.get(wtype, 0.0)))

        return WeaponProfile(
            id=weapon_id,
            name=raw["name"],
            weapon_type=wtype,
            size=wsize,
            strength=int(raw["strength"]),
            range=float(raw["range"]),
            cost=int(raw["cost"]),
            description=raw.get("description", ""),
            speed=speed,
            critical_chance_bonus=float(special.get("critical_chance_bonus", 0.0)),
            damage_per_hit=int(special.get("damage_per_hit", 1)),
            ignores_armor=bool(special.get("ignores_armor", False)),
        )
    except (KeyError, ValueError) as exc:
        logger.warning("Failed to parse weapon '%s': %s", weapon_id, exc)
        return None


class WeaponRegistry:
    """Singleton-style registry for weapon profiles."""

    _weapons: dict[str, WeaponProfile] = {}
    _loaded: bool = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True

        if not YAML_AVAILABLE:
            logger.info("PyYAML unavailable — weapon registry uses demo fallback")
            cls._load_demo_fallback()
            return

        data_dir = get_data_dir()
        if data_dir is None:
            logger.warning("Data directory not found — using demo fallback")
            cls._load_demo_fallback()
            return

        catalog_path = data_dir / "weapons" / "weapon_catalog.yaml"
        raw = load_yaml_file(catalog_path)
        if raw is None or "weapons" not in raw:
            logger.warning("weapon_catalog.yaml missing/invalid — demo fallback")
            cls._load_demo_fallback()
            return

        for weapon_id, weapon_data in raw["weapons"].items():
            profile = _parse_weapon(weapon_id, weapon_data)
            if profile is not None:
                cls._weapons[weapon_id] = profile

        logger.info("Loaded %d weapons from YAML", len(cls._weapons))

        if not cls._weapons:
            logger.warning("No weapons loaded — using demo fallback")
            cls._load_demo_fallback()

    @classmethod
    def _load_demo_fallback(cls) -> None:
        from spacefleet.data.demo_data import (
            LANCE_2,
            MACRO_CANNON_2,
            MACRO_CANNON_3,
            SALVAGE_GUN,
        )

        for wp in (MACRO_CANNON_2, MACRO_CANNON_3, LANCE_2, SALVAGE_GUN):
            cls._weapons[wp.id] = wp

    @classmethod
    def get(cls, weapon_id: str) -> WeaponProfile:
        """Look up a weapon by ID.  Raises :exc:`KeyError` if not found."""
        cls._load()
        return cls._weapons[weapon_id]

    @classmethod
    def get_or_none(cls, weapon_id: str) -> WeaponProfile | None:
        cls._load()
        return cls._weapons.get(weapon_id)

    @classmethod
    def all(cls) -> dict[str, WeaponProfile]:
        cls._load()
        return dict(cls._weapons)

    @classmethod
    def reset(cls) -> None:
        """Clear the registry (for testing)."""
        cls._weapons.clear()
        cls._loaded = False
