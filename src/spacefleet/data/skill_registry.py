"""Commander skill registry — loads from ``data/commanders/*.yaml``.

Falls back to a minimal hard-coded subset when PyYAML is unavailable
or yaml files are missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_yaml_file

if TYPE_CHECKING:
    from spacefleet.commander.abilities import AbilityDef

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PassiveSkillDef:
    id: str
    name: str
    category: str
    description: str
    effect: dict[str, Any]
    faction: str | None = None
    sprint6_dependency: bool = False


@dataclass(frozen=True)
class TraitDef:
    id: str
    name: str
    description: str
    effects: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LevelDef:
    level: int
    xp_required: int
    fleet_capacity: int
    unlocks: tuple[str, ...]
    title: str


@dataclass(frozen=True)
class CrewTierDef:
    tier: int
    name: str
    battles_required: int
    morale_bonus: int
    accuracy_bonus: float
    cooldown_reduction: float
    firepower_bonus: int = 0


_SPRINT6_ABILITY_KEYS = {"bonus_torpedo_salvo", "probe_radius"}
_SPRINT6_PASSIVE_KEYS = {
    "torpedo_speed_modifier",
    "fleet_torpedo_reload_reduction",
    "fleet_torpedo_strength",
}


class SkillRegistry:
    """Singleton-style registry for commander catalog data."""

    _actives: dict[str, AbilityDef] = {}
    _passives: dict[str, PassiveSkillDef] = {}
    _traits: dict[str, TraitDef] = {}
    _levels: dict[int, LevelDef] = {}
    _crew_tiers: dict[int, CrewTierDef] = {}
    _xp_sources: dict[str, int] = {}
    _loaded: bool = False

    @classmethod
    def ensure_loaded(cls) -> None:
        if cls._loaded:
            return
        cls._actives = {}
        cls._passives = {}
        cls._traits = {}
        cls._levels = {}
        cls._crew_tiers = {}
        cls._xp_sources = {}

        if YAML_AVAILABLE:
            cls._load_from_yaml()

        if not cls._actives:
            cls._load_fallback_actives()
        if not cls._passives:
            cls._load_fallback_passives()
        if not cls._levels:
            cls._load_fallback_levels()
        if not cls._crew_tiers:
            cls._load_fallback_crew_tiers()
        if not cls._xp_sources:
            cls._load_fallback_xp_sources()

        cls._loaded = True

    @classmethod
    def _load_from_yaml(cls) -> None:
        data_dir = get_data_dir()
        if data_dir is None:
            return
        base = data_dir / "commanders"
        if not base.is_dir():
            return

        skills_data = load_yaml_file(base / "skills.yaml") or {}
        for aid, raw in (skills_data.get("active_abilities") or {}).items():
            cls._actives[aid] = cls._parse_active(aid, raw)
        for pid, raw in (skills_data.get("passive_skills") or {}).items():
            cls._passives[pid] = cls._parse_passive(pid, raw)

        traits_data = load_yaml_file(base / "traits.yaml") or {}
        for tid, raw in (traits_data.get("traits") or {}).items():
            cls._traits[tid] = TraitDef(
                id=tid,
                name=str(raw.get("name", tid)),
                description=str(raw.get("description", "")),
                effects=dict(raw.get("effects") or {}),
            )

        level_data = load_yaml_file(base / "level_table.yaml") or {}
        for lvl_key, raw in (level_data.get("levels") or {}).items():
            lvl = int(lvl_key)
            cls._levels[lvl] = LevelDef(
                level=lvl,
                xp_required=int(raw.get("xp_required", 0)),
                fleet_capacity=int(raw.get("fleet_capacity", 0)),
                unlocks=tuple(raw.get("unlocks") or ()),
                title=str(raw.get("title", "")),
            )
        for tier_key, raw in (level_data.get("crew_experience_tiers") or {}).items():
            tier = int(tier_key)
            cls._crew_tiers[tier] = CrewTierDef(
                tier=tier,
                name=str(raw.get("name", "")),
                battles_required=int(raw.get("battles_required", 0)),
                morale_bonus=int(raw.get("morale_bonus", 0)),
                accuracy_bonus=float(raw.get("accuracy_bonus", 0.0)),
                cooldown_reduction=float(raw.get("cooldown_reduction", 0.0)),
                firepower_bonus=int(raw.get("firepower_bonus", 0)),
            )
        for key, value in (level_data.get("xp_sources") or {}).items():
            cls._xp_sources[str(key)] = int(value)

    @classmethod
    def _parse_active(cls, aid: str, raw: dict[str, Any]) -> AbilityDef:
        from spacefleet.commander.abilities import AbilityDef

        effects = dict(raw.get("effects") or {})
        is_sprint6 = bool(_SPRINT6_ABILITY_KEYS & effects.keys())
        return AbilityDef(
            id=aid,
            name=str(raw.get("name", aid)),
            category=str(raw.get("category", "universal")),
            cooldown=int(raw.get("cooldown", 0)),
            charges=int(raw.get("charges", 1)),
            preparation_turns=int(raw.get("preparation_turns", 0)),
            range_gu=float(raw["range"]) if "range" in raw else None,
            faction=str(raw.get("faction")) if raw.get("faction") else None,
            sprint6_dependency=is_sprint6,
            steps=(),
            raw_effects=effects,
        )

    @classmethod
    def _parse_passive(cls, pid: str, raw: dict[str, Any]) -> PassiveSkillDef:
        effect = dict(raw.get("effect") or {})
        is_sprint6 = bool(_SPRINT6_PASSIVE_KEYS & effect.keys())
        return PassiveSkillDef(
            id=pid,
            name=str(raw.get("name", pid)),
            category=str(raw.get("category", "universal")),
            description=str(raw.get("description", "")),
            effect=effect,
            faction=str(raw.get("faction")) if raw.get("faction") else None,
            sprint6_dependency=is_sprint6,
        )

    @classmethod
    def _load_fallback_actives(cls) -> None:
        from spacefleet.commander.abilities import AbilityDef

        cls._actives["concentrated_fire"] = AbilityDef(
            id="concentrated_fire",
            name="Concentrated Fire",
            category="universal",
            cooldown=5,
            charges=2,
            range_gu=30.0,
            steps=(),
            raw_effects={"gunnery_column_shift": 1, "duration": 2},
        )
        cls._actives["emergency_repairs"] = AbilityDef(
            id="emergency_repairs",
            name="Emergency Repairs",
            category="universal",
            cooldown=4,
            charges=2,
            steps=(),
            raw_effects={
                "hull_restore": "D3",
                "extinguish_fires": True,
                "repair_temp_crit": 1,
            },
        )
        cls._actives["call_to_arms"] = AbilityDef(
            id="call_to_arms",
            name="Call to Arms",
            category="universal",
            cooldown=5,
            charges=3,
            range_gu=40.0,
            steps=(),
            raw_effects={"morale_restore": 30, "cancel_mutiny": True},
        )

    @classmethod
    def _load_fallback_passives(cls) -> None:
        cls._passives["veteran_crews"] = PassiveSkillDef(
            id="veteran_crews",
            name="Veteran Crews",
            category="universal",
            description="Fleet-wide morale loss reduced by 25%.",
            effect={"morale_loss_reduction": 0.25},
        )
        cls._passives["master_gunner"] = PassiveSkillDef(
            id="master_gunner",
            name="Master Gunner",
            category="universal",
            description="+1 firepower at close range.",
            effect={"close_range_battery_bonus": 1},
        )

    @classmethod
    def _load_fallback_levels(cls) -> None:
        cls._levels[1] = LevelDef(
            level=1, xp_required=0, fleet_capacity=400, unlocks=(), title="Sub-Admiral"
        )
        cls._levels[2] = LevelDef(
            level=2, xp_required=150, fleet_capacity=500, unlocks=(), title="Sub-Admiral"
        )
        cls._levels[3] = LevelDef(
            level=3, xp_required=400, fleet_capacity=650, unlocks=(), title="Admiral"
        )

    @classmethod
    def _load_fallback_crew_tiers(cls) -> None:
        cls._crew_tiers[0] = CrewTierDef(
            tier=0,
            name="Green",
            battles_required=0,
            morale_bonus=0,
            accuracy_bonus=0.0,
            cooldown_reduction=0.0,
        )
        cls._crew_tiers[1] = CrewTierDef(
            tier=1,
            name="Trained",
            battles_required=2,
            morale_bonus=5,
            accuracy_bonus=0.0,
            cooldown_reduction=0.05,
        )

    @classmethod
    def _load_fallback_xp_sources(cls) -> None:
        cls._xp_sources = {
            "battle_victory": 100,
            "battle_defeat_survived": 30,
            "enemy_capital_destroyed": 25,
            "enemy_escort_destroyed": 10,
            "objective_completed": 50,
            "story_mission_completed": 100,
            "first_blood": 15,
        }

    @classmethod
    def get_active(cls, ability_id: str) -> AbilityDef | None:
        cls.ensure_loaded()
        return cls._actives.get(ability_id)

    @classmethod
    def get_passive(cls, passive_id: str) -> PassiveSkillDef | None:
        cls.ensure_loaded()
        return cls._passives.get(passive_id)

    @classmethod
    def get_trait(cls, trait_id: str) -> TraitDef | None:
        cls.ensure_loaded()
        return cls._traits.get(trait_id)

    @classmethod
    def get_level(cls, level: int) -> LevelDef | None:
        cls.ensure_loaded()
        return cls._levels.get(level)

    @classmethod
    def get_crew_tier(cls, tier: int) -> CrewTierDef | None:
        cls.ensure_loaded()
        return cls._crew_tiers.get(tier)

    @classmethod
    def xp_source(cls, key: str) -> int:
        cls.ensure_loaded()
        return cls._xp_sources.get(key, 0)

    @classmethod
    def all_active_ids(cls) -> tuple[str, ...]:
        cls.ensure_loaded()
        return tuple(cls._actives.keys())

    @classmethod
    def all_passive_ids(cls) -> tuple[str, ...]:
        cls.ensure_loaded()
        return tuple(cls._passives.keys())

    @classmethod
    def all_trait_ids(cls) -> tuple[str, ...]:
        cls.ensure_loaded()
        return tuple(cls._traits.keys())

    @classmethod
    def all_crew_tiers(cls) -> tuple[CrewTierDef, ...]:
        cls.ensure_loaded()
        return tuple(cls._crew_tiers[t] for t in sorted(cls._crew_tiers))
