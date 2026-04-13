"""Upgrade catalog loaded from ``data/upgrades/upgrades.yaml``.

Falls back to a small inline set when YAML is unavailable so tests
and headless runs still work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_yaml_file

logger = logging.getLogger(__name__)


def _coerce_effect_value(value: Any) -> Any:
    """YAML loads ``+1`` as the string ``"+1"``; coerce to int when possible."""
    if isinstance(value, str) and value.startswith(("+", "-")):
        try:
            return int(value)
        except ValueError:
            return value
    return value


@dataclass(frozen=True)
class UpgradeProfile:
    """Immutable upgrade definition."""

    id: str
    name: str
    category: str
    cost: int
    description: str = ""
    effect: dict[str, Any] = field(default_factory=dict)


def _parse(upgrade_id: str, raw: dict[str, Any]) -> UpgradeProfile | None:
    try:
        effect_raw: dict[str, Any] = raw.get("effect") or {}
        effect = {k: _coerce_effect_value(v) for k, v in effect_raw.items()}
        return UpgradeProfile(
            id=upgrade_id,
            name=str(raw["name"]),
            category=str(raw.get("category", "misc")),
            cost=int(raw["cost"]),
            description=str(raw.get("description", "")),
            effect=effect,
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse upgrade %s: %s", upgrade_id, exc)
        return None


_DEMO_UPGRADES: dict[str, UpgradeProfile] = {
    "additional_void_shield": UpgradeProfile(
        id="additional_void_shield",
        name="Additional Void Shield",
        category="defensive",
        cost=30,
        description="An extra void shield generator. +1 shield capacity.",
        effect={"shields": 1},
    ),
    "fire_suppression_system": UpgradeProfile(
        id="fire_suppression_system",
        name="Fire Suppression System",
        category="defensive",
        cost=15,
        description="Automated fire control.",
        effect={"fire_extinguish_chance": 0.50},
    ),
}


class UpgradeRegistry:
    """Singleton-style registry for ship upgrades."""

    _upgrades: dict[str, UpgradeProfile] = {}
    _loaded: bool = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True

        if not YAML_AVAILABLE:
            cls._upgrades.update(_DEMO_UPGRADES)
            return

        data_dir = get_data_dir()
        if data_dir is None:
            cls._upgrades.update(_DEMO_UPGRADES)
            return

        path = data_dir / "upgrades" / "upgrades.yaml"
        raw = load_yaml_file(path)
        if raw is None or "upgrades" not in raw:
            cls._upgrades.update(_DEMO_UPGRADES)
            return

        for upgrade_id, data in raw["upgrades"].items():
            up = _parse(upgrade_id, data)
            if up is not None:
                cls._upgrades[upgrade_id] = up

        if not cls._upgrades:
            cls._upgrades.update(_DEMO_UPGRADES)

    @classmethod
    def get(cls, upgrade_id: str) -> UpgradeProfile:
        cls._load()
        return cls._upgrades[upgrade_id]

    @classmethod
    def get_or_none(cls, upgrade_id: str) -> UpgradeProfile | None:
        cls._load()
        return cls._upgrades.get(upgrade_id)

    @classmethod
    def all(cls) -> dict[str, UpgradeProfile]:
        cls._load()
        return dict(cls._upgrades)

    @classmethod
    def reset(cls) -> None:
        cls._upgrades.clear()
        cls._loaded = False
