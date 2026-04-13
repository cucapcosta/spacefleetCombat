"""Stance data registry — loads from ``data/stances/stances.yaml``.

Falls back to inline definitions when YAML is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_yaml_file

if TYPE_CHECKING:
    from spacefleet.core.types import Stance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StanceData:
    """Flat modifier bag for a single stance."""

    id: str
    name: str
    description: str = ""
    switch_cooldown: int = 0
    # Offensive
    gunnery_column_shift: int = 0  # +1 Lock On, -1 Reload
    lance_reroll_misses: bool = False
    critical_chance_bonus: float = 0.0
    battery_strength_bonus: int = 0  # +1 for Reload
    # Defensive
    extra_armor_save: int = 0  # 0 = none, 6 = save on 6+
    hull_damage_reduction: float = 0.0  # 0.25 = -25%
    turret_accuracy_bonus: float = 0.0
    weapon_strength_modifier: float = 1.0  # 0.5 for Brace
    # Detection
    detection_signature_modifier: float = 1.0  # 0.5 for Running Silent
    own_sensor_range_modifier: float = 1.0  # 0.5 for Running Silent
    # Restrictions
    cannot_fire: bool = False
    breaks_on_fire: bool = False


# ── Inline fallback definitions ──────────────────────────────

_DEMO_STANCES: dict[str, StanceData] = {
    "standard": StanceData(
        id="standard",
        name="Standard",
        description="No bonuses or penalties.",
    ),
    "lock_on": StanceData(
        id="lock_on",
        name="Lock On",
        description="Improved gunnery accuracy and lance re-rolls.",
        switch_cooldown=2,
        gunnery_column_shift=1,
        lance_reroll_misses=True,
        critical_chance_bonus=0.25,
    ),
    "brace_for_impact": StanceData(
        id="brace_for_impact",
        name="Brace for Impact",
        description="Extra armor saves at the cost of firepower.",
        switch_cooldown=2,
        extra_armor_save=6,
        hull_damage_reduction=0.25,
        turret_accuracy_bonus=0.50,
        weapon_strength_modifier=0.5,
    ),
    "reload": StanceData(
        id="reload",
        name="Reload",
        description="Battery strength bonus but reduced accuracy.",
        switch_cooldown=2,
        gunnery_column_shift=-1,
        battery_strength_bonus=1,
    ),
    "running_silent": StanceData(
        id="running_silent",
        name="Running Silent",
        description="Reduced detection signature; cannot fire.",
        switch_cooldown=3,
        detection_signature_modifier=0.5,
        own_sensor_range_modifier=0.5,
        cannot_fire=True,
        breaks_on_fire=True,
    ),
}


def _parse_stance(raw: dict) -> StanceData | None:  # type: ignore[type-arg]
    """Parse a stance entry from the YAML effects block."""
    try:
        sid = raw["id"]
        effects = raw.get("effects") or {}
        return StanceData(
            id=sid,
            name=raw.get("name", sid.replace("_", " ").title()),
            description=raw.get("description", ""),
            switch_cooldown=int(raw.get("switch_cooldown", 0)),
            gunnery_column_shift=int(effects.get("gunnery_column_shift", 0)),
            lance_reroll_misses=bool(effects.get("lance_reroll_misses", False)),
            critical_chance_bonus=float(effects.get("critical_chance_bonus", 0.0)),
            battery_strength_bonus=int(effects.get("battery_strength_bonus", 0)),
            extra_armor_save=int(effects.get("extra_armor_save", 0)),
            hull_damage_reduction=float(effects.get("hull_damage_reduction", 0.0)),
            turret_accuracy_bonus=float(effects.get("turret_accuracy_bonus", 0.0)),
            weapon_strength_modifier=float(effects.get("weapon_strength_modifier", 1.0)),
            detection_signature_modifier=float(effects.get("detection_signature_modifier", 1.0)),
            own_sensor_range_modifier=float(effects.get("own_sensor_range_modifier", 1.0)),
            cannot_fire=bool(effects.get("cannot_fire", False)),
            breaks_on_fire=bool(effects.get("breaks_on_fire", False)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse stance '%s': %s", raw.get("id", "?"), exc)
        return None


class StanceRegistry:
    """Singleton registry for stance data."""

    _stances: dict[str, StanceData] = {}
    _loaded: bool = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True

        if YAML_AVAILABLE:
            data_dir = get_data_dir()
            if data_dir is not None:
                path = data_dir / "stances" / "stances.yaml"
                raw = load_yaml_file(path)
                if raw is not None and isinstance(raw, dict):
                    # YAML is dict-of-dicts keyed by stance ID
                    stances_dict = raw.get("stances", {})
                    if isinstance(stances_dict, dict):
                        for sid, entry in stances_dict.items():
                            if isinstance(entry, dict):
                                entry["id"] = sid
                                parsed = _parse_stance(entry)
                                if parsed is not None:
                                    cls._stances[parsed.id] = parsed
                    if cls._stances:
                        logger.info("Loaded %d stances from YAML", len(cls._stances))
                        return

        logger.info("Using inline stance definitions")
        cls._stances.update(_DEMO_STANCES)

    @classmethod
    def get(cls, stance_id: str) -> StanceData:
        """Look up stance data by ID.  Raises KeyError if not found."""
        cls._load()
        return cls._stances[stance_id]

    @classmethod
    def get_for(cls, stance: Stance) -> StanceData:
        """Look up stance data by enum value."""
        return cls.get(stance.value)

    @classmethod
    def all(cls) -> dict[str, StanceData]:
        cls._load()
        return dict(cls._stances)

    @classmethod
    def reset(cls) -> None:
        """Clear (for testing)."""
        cls._stances.clear()
        cls._loaded = False
