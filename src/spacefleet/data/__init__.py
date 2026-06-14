"""Data layer — YAML-backed registries with inline demo fallback."""

from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.weapon_registry import WeaponRegistry

__all__ = ["DoctrineRegistry", "HullRegistry", "WeaponRegistry"]
