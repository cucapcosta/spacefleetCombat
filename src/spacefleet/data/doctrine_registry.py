"""Doctrine catalog — loads from ``data/doctrines/doctrines.yaml``.

Per-ship faction doctrines.  Falls back to an inline table when PyYAML or
the data file is unavailable, matching the other registries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_yaml_file

if TYPE_CHECKING:
    from spacefleet.core.types import Faction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DoctrineDef:
    id: str
    name: str
    faction: str
    cost: int
    description: str = ""
    column_shift: int = 0
    lance_threshold: int | None = None
    assault_bonus: int = 0
    board_immune: bool = False
    morale_floor: int = 0
    hull_delta: int = 0
    speed_delta: float = 0.0
    shield_delta: int = 0
    lances_allowed: bool = True
    upgrade_slot_bonus: int = 0


def _parse(did: str, raw: dict[str, Any]) -> DoctrineDef:
    return DoctrineDef(
        id=did,
        name=str(raw.get("name", did)),
        faction=str(raw["faction"]),
        cost=int(raw.get("cost", 0)),
        description=str(raw.get("description", "")),
        column_shift=int(raw.get("column_shift", 0)),
        lance_threshold=(
            int(raw["lance_threshold"]) if raw.get("lance_threshold") is not None else None
        ),
        assault_bonus=int(raw.get("assault_bonus", 0)),
        board_immune=bool(raw.get("board_immune", False)),
        morale_floor=int(raw.get("morale_floor", 0)),
        hull_delta=int(raw.get("hull_delta", 0)),
        speed_delta=float(raw.get("speed_delta", 0.0)),
        shield_delta=int(raw.get("shield_delta", 0)),
        lances_allowed=bool(raw.get("lances_allowed", True)),
        upgrade_slot_bonus=int(raw.get("upgrade_slot_bonus", 0)),
    )


class DoctrineRegistry:
    _items: dict[str, DoctrineDef] = {}
    _loaded: bool = False

    @classmethod
    def _load(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True
        cls._items = {}
        if YAML_AVAILABLE:
            data_dir = get_data_dir()
            if data_dir is not None:
                raw = load_yaml_file(data_dir / "doctrines" / "doctrines.yaml")
                if raw:
                    for did, body in (raw.get("doctrines") or {}).items():
                        cls._items[did] = _parse(did, body)
        if not cls._items:
            logger.warning("doctrines.yaml missing/invalid — using inline fallback")
            cls._load_fallback()

    @classmethod
    def _load_fallback(cls) -> None:
        defs = [
            DoctrineDef(
                "navy_gunnery_school",
                "Navy Gunnery School",
                "imperial_navy",
                15,
                column_shift=1,
            ),
            DoctrineDef("commissariat", "Commissariat", "imperial_navy", 15, morale_floor=20),
            DoctrineDef(
                "space_marine_detachment",
                "Space Marine Detachment",
                "imperial_navy",
                25,
                assault_bonus=2,
                board_immune=True,
            ),
            DoctrineDef(
                "mechanicus_rites",
                "Mechanicus Rites",
                "imperial_navy",
                20,
                upgrade_slot_bonus=1,
            ),
            DoctrineDef(
                "mark_of_khorne",
                "Mark of Khorne",
                "chaos_fleet",
                25,
                assault_bonus=3,
                lances_allowed=False,
            ),
            DoctrineDef(
                "mark_of_tzeentch",
                "Mark of Tzeentch",
                "chaos_fleet",
                25,
                lance_threshold=3,
                hull_delta=-1,
            ),
            DoctrineDef(
                "mark_of_nurgle",
                "Mark of Nurgle",
                "chaos_fleet",
                15,
                hull_delta=2,
                speed_delta=-5.0,
            ),
            DoctrineDef(
                "mark_of_slaanesh",
                "Mark of Slaanesh",
                "chaos_fleet",
                15,
                speed_delta=10.0,
                shield_delta=-1,
            ),
        ]
        cls._items = {d.id: d for d in defs}

    @classmethod
    def all(cls) -> dict[str, DoctrineDef]:
        cls._load()
        return dict(cls._items)

    @classmethod
    def get(cls, doctrine_id: str) -> DoctrineDef:
        cls._load()
        return cls._items[doctrine_id]

    @classmethod
    def get_or_none(cls, doctrine_id: str | None) -> DoctrineDef | None:
        if doctrine_id is None:
            return None
        cls._load()
        return cls._items.get(doctrine_id)

    @classmethod
    def for_faction(cls, faction: Faction) -> list[DoctrineDef]:
        cls._load()
        return [d for d in cls._items.values() if d.faction == faction.value]

    @classmethod
    def reset(cls) -> None:
        cls._items = {}
        cls._loaded = False
