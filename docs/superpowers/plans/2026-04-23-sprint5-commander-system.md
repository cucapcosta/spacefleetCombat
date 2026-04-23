# Sprint 5 Commander System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Commander layer on top of Sprint 1–4 — per-fleet Commander entity with active abilities (declarative effect-step primitives, cooldown/charge-gated) and passive skills (named-hook dispatcher), per-ship crew veterancy, new command sub-phase at the start of each turn, automatic XP + crew-tier awards on battle end, and default commander auto-assigned to every fleet in existing scenarios.

**Architecture:** Five new modules under `src/spacefleet/commander/` + `src/spacefleet/data/skill_registry.py` + `src/spacefleet/phases/command_phase.py`. `Fleet` and `Ship` gain fields; `CoreGameState` gets `fleets: dict[str, Fleet]`. Passives apply through a `PassiveBus` built once per turn (rebuilt after the command phase). `resolve_turn` gains an `ability_orders` channel, runs the command phase first, then existing fire/movement/end-of-turn sub-phases with hook dispatches at well-defined points.

**Tech Stack:** Python 3.12, dataclasses with `field(default_factory=...)`, PyYAML (optional), pytest, ruff, mypy `--strict`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-23-sprint5-commander-system-design.md`.

---

## Out of scope

- Trait earning (Sprint 9 narrative concern — `traits.yaml` loads but acquisition is manual via commander construction).
- Fleet builder CLI (Sprint 6).
- Torpedo + detection integration for `torpedo_barrage` / `augur_probe` / torpedo-related passives — registered as no-op stubs.
- Replacing `player_ships: dict[str, list[str]]`; `state.fleets` lives alongside it.
- Campaign persistence (Sprint 8/9).

---

## Conventions every task follows

- All edits stay on a single feature branch off `main` named `feature/sprint5-commander`.
- TDD: failing test → run → impl → run → commit. Every task ends with:
  - `uv run pytest -q` (all pass, +N new)
  - `uv run ruff check src tests` (clean)
  - `uv run ruff format --check src tests` (clean — run `uv run ruff format src tests` if it complains, re-stage, re-commit as part of same task)
  - `uv run mypy --strict src` (clean)
- Commits use Conventional Commits (`feat:`, `refactor:`, `fix:`, `test:`).
- Commit message HEREDOC. No `Co-Authored-By` trailer. No AI attribution footers.
- All commands run from repo root with `uv run`.

---

## File map

**Create:**
- `src/spacefleet/commander/__init__.py` — re-exports
- `src/spacefleet/commander/commander.py` — `Commander`, `AbilityState`, `ActiveBuff`
- `src/spacefleet/commander/abilities.py` — effect-step dataclasses, `AbilityDef`, `resolve_ability`, `PendingSprint6Event`
- `src/spacefleet/commander/passive_skills.py` — `PassiveHook`, `PassiveContext`, `PassiveBus`, handler registry (universal + faction + crew-tier + sprint6-inert)
- `src/spacefleet/commander/progression.py` — `LevelDef`, `CrewTierDef`, `apply_xp`, `compute_battle_xp`, `bump_crew_veterancy`, `crew_tier_for`, `XpGainedEvent`, `LevelUpEvent`, `CrewTierUpEvent`
- `src/spacefleet/data/skill_registry.py` — `SkillRegistry` + yaml→effect-step parser + fallback
- `src/spacefleet/phases/command_phase.py` — `AbilityOrder`, `AbilityRejectedEvent`, `AbilityUsedEvent`, `AbilityPrepStartedEvent`, `AbilityInterruptedEvent`, `BuffExpiredEvent`, `resolve_command_phase`

**Modify:**
- `src/spacefleet/models/ship.py` — `battles_survived` field, `crew_tier` property, `apply_morale_change(delta, state=None)` passive-aware
- `src/spacefleet/models/fleet.py` — `commander`, `flagship_ship_id`, `ship_ids`, `ships_in`, `alive_ships_in`, `flagship_in`
- `src/spacefleet/core/game_state.py` — `fleets: dict[str, Fleet]`, `fleet_of(ship)`
- `src/spacefleet/net/commands.py` — `AbilityOrder` dataclass
- `src/spacefleet/net/game_state.py` — `_class_weight`, `_build_starter_commander`, `_assign_default_commander` called from `_add_imperial_fleet`/`_add_chaos_fleet`
- `src/spacefleet/net/turn_resolver.py` — signature `ability_orders`, command phase call, `PassiveBus` build/rebuild, hook dispatch at fire/end-of-turn, battle-end XP + veterancy
- `src/spacefleet/phases/movement_phase.py` — use `effective_speed_max_with_passives(ship, state)`
- `src/spacefleet/combat/resolution.py` — `resolve_battery_attack(state=None)`, dispatch `HIT_COLUMN_SHIFT` + `BATTERY_FIREPOWER_BONUS` when state given
- `src/spacefleet/combat/projectile_resolution.py` — same pattern for ray resolution
- `src/spacefleet/combat/lance.py` — dispatch `LANCE_HIT_THRESHOLD` when state given
- `src/spacefleet/combat/critical_hits.py` — dispatch `HULL_BREACH_APPLY` when state given
- `src/spacefleet/combat/morale_effects.py` — pass `state` into `ship.apply_morale_change`
- `src/spacefleet/cli/game_cmd.py` — `ability` command parser
- `src/spacefleet/core/events.py` — no change (new events are `TurnEvent` subclasses defined in their owning modules)

**Create tests (each is its own file, grouped at end of plan):** see Task-level Test block below each task.

---

## Branch setup (run once)

```bash
git checkout main
git pull
git checkout -b feature/sprint5-commander
```

---

## Task 1: SkillRegistry + types + fallback

Ground the registry as a loader: typed defs for every catalog (active, passive, trait, level, crew tier, xp_source), yaml-first with fallback to a minimal hard-coded subset. No effect-step parsing yet — that's Task 8.

**Files:**
- Create: `src/spacefleet/data/skill_registry.py`
- Create: `tests/test_skill_registry_fallback.py`
- Create: `tests/test_skill_registry_yaml.py`

- [ ] **Step 1: Write failing fallback test**

Create `tests/test_skill_registry_fallback.py`:

```python
"""Registry still works when PyYAML is unavailable / yaml dir missing."""

from __future__ import annotations

from unittest.mock import patch

from spacefleet.data import skill_registry


def test_fallback_populates_universal_abilities() -> None:
    # Force a fresh load with yaml disabled
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    ids = skill_registry.SkillRegistry.all_active_ids()
    assert "concentrated_fire" in ids
    assert "emergency_repairs" in ids
    assert "call_to_arms" in ids


def test_fallback_populates_universal_passives() -> None:
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    ids = skill_registry.SkillRegistry.all_passive_ids()
    assert "veteran_crews" in ids
    assert "master_gunner" in ids


def test_fallback_levels_and_crew_tiers_present() -> None:
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    lvl2 = skill_registry.SkillRegistry.get_level(2)
    assert lvl2 is not None
    assert lvl2.xp_required > 0

    tier0 = skill_registry.SkillRegistry.get_crew_tier(0)
    assert tier0 is not None
    assert tier0.battles_required == 0


def test_xp_sources_loaded() -> None:
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    assert skill_registry.SkillRegistry.xp_source("battle_victory") > 0
```

- [ ] **Step 2: Write failing yaml test**

Create `tests/test_skill_registry_yaml.py`:

```python
"""Registry loads the real YAML data under data/commanders/."""

from __future__ import annotations

from spacefleet.data import skill_registry


def test_yaml_loads_all_known_actives() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    ids = skill_registry.SkillRegistry.all_active_ids()
    # All 10 active abilities from skills.yaml should be present
    for expected in (
        "micro_warp_jump",
        "emergency_repairs",
        "call_to_arms",
        "augur_probe",
        "concentrated_fire",
        "torpedo_barrage",
        "boarding_assault",
        "warp_rift",
        "mark_of_chaos",
    ):
        assert expected in ids, f"missing ability: {expected}"


def test_yaml_marks_sprint6_dependencies() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    torp = skill_registry.SkillRegistry.get_active("torpedo_barrage")
    assert torp is not None
    assert torp.sprint6_dependency is True

    probe = skill_registry.SkillRegistry.get_active("augur_probe")
    assert probe is not None
    assert probe.sprint6_dependency is True

    er = skill_registry.SkillRegistry.get_active("emergency_repairs")
    assert er is not None
    assert er.sprint6_dependency is False


def test_yaml_loads_level_and_crew_tier_tables() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    for lvl in range(1, 11):
        assert skill_registry.SkillRegistry.get_level(lvl) is not None

    for tier in range(0, 5):
        assert skill_registry.SkillRegistry.get_crew_tier(tier) is not None


def test_yaml_loads_traits() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    assert "veteran_of_cadia" in skill_registry.SkillRegistry.all_trait_ids()
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
uv run pytest tests/test_skill_registry_fallback.py tests/test_skill_registry_yaml.py -v
```
Expected: ImportError / ModuleNotFoundError on `spacefleet.data.skill_registry`.

- [ ] **Step 4: Write minimal registry module**

Create `src/spacefleet/data/skill_registry.py`:

```python
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
    from spacefleet.commander.abilities import AbilityDef, EffectStep

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

    # ── Loading ────────────────────────────────────────────

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

        # Fallback if yaml loading produced nothing
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
        from spacefleet.commander.abilities import AbilityDef  # local import

        effects = dict(raw.get("effects") or {})
        is_sprint6 = bool(_SPRINT6_ABILITY_KEYS & effects.keys())
        # Steps are populated by Task 8; leave empty for now.
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

    # ── Fallbacks ──────────────────────────────────────────

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

    # ── Public accessors ───────────────────────────────────

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
```

Note: This depends on `spacefleet.commander.abilities.AbilityDef` which Task 7 creates. For Task 1 to pass its tests, Task 7's `AbilityDef` must be created first OR Task 1 must stub `AbilityDef` locally. **Build order choice:** create a minimal `commander/abilities.py` stub with just `AbilityDef` first (no effect-step logic). Add to Task 1 steps below.

- [ ] **Step 5: Write minimal AbilityDef stub**

Create `src/spacefleet/commander/__init__.py` (empty):

```python
"""Commander layer: entity, abilities, passive skills, progression."""
```

Create `src/spacefleet/commander/abilities.py` (stub — full impl in Task 7):

```python
"""Commander active abilities — effect-step primitives and resolver.

Task 1 stub: only ``AbilityDef`` dataclass is defined here.  Effect steps
and ``resolve_ability`` are introduced in later tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EffectStep = Any  # refined in Task 7


@dataclass(frozen=True)
class AbilityDef:
    id: str
    name: str
    category: str
    cooldown: int
    charges: int
    preparation_turns: int = 0
    range_gu: float | None = None
    faction: str | None = None
    sprint6_dependency: bool = False
    steps: tuple[EffectStep, ...] = field(default_factory=tuple)
    raw_effects: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 6: Export skill_registry from spacefleet.data**

Modify `src/spacefleet/data/__init__.py` — add re-export if not already barrel-exporting:

```python
# existing contents unchanged; if HullRegistry etc are exported, add:
from spacefleet.data.skill_registry import SkillRegistry as SkillRegistry
```

If `spacefleet/data/__init__.py` is empty or non-barrel, just import via full path in tests (`from spacefleet.data import skill_registry`). Leave `__init__.py` alone in that case.

- [ ] **Step 7: Run tests — expect pass**

```bash
uv run pytest tests/test_skill_registry_fallback.py tests/test_skill_registry_yaml.py -v
```
Expected: all 8 pass.

- [ ] **Step 8: Run full gate**

```bash
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
```
All green. If `ruff format --check` fails, run `uv run ruff format src tests` and re-stage.

- [ ] **Step 9: Commit**

```bash
git add src/spacefleet/commander/__init__.py \
        src/spacefleet/commander/abilities.py \
        src/spacefleet/data/skill_registry.py \
        tests/test_skill_registry_fallback.py \
        tests/test_skill_registry_yaml.py
# also add src/spacefleet/data/__init__.py if touched
git commit -m "$(cat <<'EOF'
feat(commander): SkillRegistry with yaml + fallback loader

Loads commander skills, traits, level table, crew tiers, xp sources
from data/commanders/*.yaml.  Falls back to a minimal hard-coded
subset when PyYAML unavailable or yaml files missing.

Effect-step parsing and AbilityDef.steps population come in later
tasks (7, 8) when the step primitives exist.
EOF
)"
```

---

## Task 2: Progression math

`crew_tier_for` + `apply_xp` with multi-level overflow + cap at level 10. Events published by callers (Task 25); this task just gives pure math.

**Files:**
- Create: `src/spacefleet/commander/progression.py`
- Create: `tests/test_progression_xp.py`
- Create: `tests/test_progression_crew_tier.py`

- [ ] **Step 1: Write failing XP test**

Create `tests/test_progression_xp.py`:

```python
"""Commander XP + level up math."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.commander.progression import apply_xp
from spacefleet.core.types import Faction
from spacefleet.data.skill_registry import SkillRegistry


def _make_cmdr() -> Commander:
    return Commander(
        id="c1",
        name="Test Commander",
        faction=Faction.IMPERIAL_NAVY,
        level=1,
        xp=0,
    )


def test_apply_xp_below_threshold_stays_at_level() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    events = apply_xp(cmdr, 50)
    assert cmdr.level == 1
    assert cmdr.xp == 50
    # XP gained event but no level up
    assert any(ev.__class__.__name__ == "XpGainedEvent" for ev in events)
    assert not any(ev.__class__.__name__ == "LevelUpEvent" for ev in events)


def test_apply_xp_single_level_up() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    events = apply_xp(cmdr, 200)  # level 2 requires 150
    assert cmdr.level == 2
    assert cmdr.xp == 200
    level_ups = [ev for ev in events if ev.__class__.__name__ == "LevelUpEvent"]
    assert len(level_ups) == 1


def test_apply_xp_multi_level_overflow() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    # With yaml, level 3 requires 400. Jumping 500 should skip from 1→3.
    events = apply_xp(cmdr, 500)
    assert cmdr.level >= 3
    level_ups = [ev for ev in events if ev.__class__.__name__ == "LevelUpEvent"]
    assert len(level_ups) >= 2


def test_apply_xp_capped_at_level_10() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    apply_xp(cmdr, 999_999)
    assert cmdr.level == 10
```

- [ ] **Step 2: Write failing crew-tier test**

Create `tests/test_progression_crew_tier.py`:

```python
"""Crew tier derivation + increment."""

from __future__ import annotations

from spacefleet.commander.progression import (
    bump_crew_veterancy,
    crew_tier_for,
)
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.models.ship import Ship


def test_crew_tier_for_lookup() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    assert crew_tier_for(0) == 0
    assert crew_tier_for(2) == 1        # Trained: battles_required 2
    assert crew_tier_for(5) == 2        # Experienced
    assert crew_tier_for(100) == 4      # Elite cap


def test_bump_crew_veterancy_advances_tier() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    ship = Ship.from_profile(
        "s1", "Test Ship", HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )
    ship.battles_survived = 1
    assert ship.crew_tier == 0

    events = bump_crew_veterancy(ship)
    assert ship.battles_survived == 2
    assert ship.crew_tier == 1
    assert any(ev.__class__.__name__ == "CrewTierUpEvent" for ev in events)


def test_bump_without_tier_change_emits_no_event() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    ship = Ship.from_profile(
        "s1", "Test Ship", HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )
    ship.battles_survived = 0
    events = bump_crew_veterancy(ship)
    assert ship.battles_survived == 1
    assert ship.crew_tier == 0
    assert not any(ev.__class__.__name__ == "CrewTierUpEvent" for ev in events)
```

Note: This test references `Commander`, `Ship.battles_survived`, `Ship.crew_tier`. Tasks 3 and 5 add those. Order-of-build: Task 2's tests won't pass until Tasks 3+5 land. Keep the test file but xfail-skip until Task 5 completes. **Simpler approach:** reorder — do Tasks 3 and 5 before finishing Task 2.

**Build order override for Task 2:** do Steps 1–2 (write tests), then stop. Do Tasks 3 and 5 (Commander + Ship fields). Return here and complete Steps 3–8.

- [ ] **Step 3: Write progression implementation** (after Tasks 3, 5 land)

Create `src/spacefleet/commander/progression.py`:

```python
"""Commander XP/level math + ship crew veterancy tracking.

Pure functions.  Events are returned as a list; callers (turn_resolver)
publish them on ``state.events``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.core.events import Event
from spacefleet.data.skill_registry import SkillRegistry

if TYPE_CHECKING:
    from spacefleet.commander.commander import Commander
    from spacefleet.models.ship import Ship


MAX_LEVEL = 10
MAX_CREW_TIER = 4


@dataclass
class XpGainedEvent(Event):
    commander_id: str
    amount: int
    total_xp: int


@dataclass
class LevelUpEvent(Event):
    commander_id: str
    new_level: int
    unlocks: tuple[str, ...]
    title: str


@dataclass
class CrewTierUpEvent(Event):
    ship_id: str
    old_tier: int
    new_tier: int


def apply_xp(commander: Commander, amount: int) -> list[Event]:
    """Add *amount* xp to *commander*, level up as many times as xp allows."""
    events: list[Event] = []
    if amount <= 0:
        return events
    commander.xp += amount
    events.append(
        XpGainedEvent(
            commander_id=commander.id,
            amount=amount,
            total_xp=commander.xp,
        )
    )
    while commander.level < MAX_LEVEL:
        nxt = SkillRegistry.get_level(commander.level + 1)
        if nxt is None or commander.xp < nxt.xp_required:
            break
        commander.level += 1
        events.append(
            LevelUpEvent(
                commander_id=commander.id,
                new_level=commander.level,
                unlocks=tuple(nxt.unlocks),
                title=nxt.title,
            )
        )
    return events


def crew_tier_for(battles_survived: int) -> int:
    """Return highest tier whose ``battles_required <= battles_survived``."""
    tiers = SkillRegistry.all_crew_tiers()
    best = 0
    for t in tiers:
        if battles_survived >= t.battles_required:
            best = t.tier
    return min(best, MAX_CREW_TIER)


def bump_crew_veterancy(ship: Ship) -> list[Event]:
    """+1 battles_survived.  Emit ``CrewTierUpEvent`` if tier advanced."""
    events: list[Event] = []
    old_tier = ship.crew_tier
    ship.battles_survived += 1
    new_tier = ship.crew_tier
    if new_tier != old_tier:
        events.append(
            CrewTierUpEvent(
                ship_id=ship.id,
                old_tier=old_tier,
                new_tier=new_tier,
            )
        )
    return events


def compute_battle_xp_for_fleet(
    fleet_kill_capitals: int,
    fleet_kill_escorts: int,
    won: bool,
    survived: bool,
    first_blood: bool,
) -> int:
    """Pure computation: XP a single fleet earns from a finished battle."""
    xp = 0
    if won:
        xp += SkillRegistry.xp_source("battle_victory")
    elif survived:
        xp += SkillRegistry.xp_source("battle_defeat_survived")
    xp += fleet_kill_capitals * SkillRegistry.xp_source("enemy_capital_destroyed")
    xp += fleet_kill_escorts * SkillRegistry.xp_source("enemy_escort_destroyed")
    if first_blood:
        xp += SkillRegistry.xp_source("first_blood")
    return xp
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_progression_xp.py tests/test_progression_crew_tier.py -v
```
Expected: all pass (after Tasks 3, 5 complete).

- [ ] **Step 5: Full gate + commit**

```bash
uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src
git add src/spacefleet/commander/progression.py \
        tests/test_progression_xp.py \
        tests/test_progression_crew_tier.py
git commit -m "$(cat <<'EOF'
feat(commander): XP / level-up / crew-tier progression math

apply_xp handles multi-level overflow, caps at level 10.
crew_tier_for walks the tier table.  bump_crew_veterancy emits
CrewTierUpEvent on transition.  compute_battle_xp_for_fleet is a
pure helper — callers assemble the inputs.
EOF
)"
```

---

## Task 3: Commander entity + AbilityState + ActiveBuff

**Files:**
- Create: `src/spacefleet/commander/commander.py`
- Create: `tests/test_commander_entity.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_commander_entity.py`:

```python
"""Commander dataclass + AbilityState + ActiveBuff construction."""

from __future__ import annotations

from spacefleet.commander.commander import (
    AbilityState,
    ActiveBuff,
    Commander,
)
from spacefleet.core.types import Faction


def test_commander_defaults() -> None:
    c = Commander(id="c1", name="Admiral", faction=Faction.IMPERIAL_NAVY)
    assert c.level == 1
    assert c.xp == 0
    assert c.active_ability_ids == []
    assert c.passive_skill_ids == []
    assert c.trait_ids == []
    assert c.ability_state == {}
    assert c.active_buffs == []


def test_ability_state_defaults() -> None:
    st = AbilityState(remaining_charges=3)
    assert st.remaining_charges == 3
    assert st.cooldown_remaining == 0
    assert st.preparation_turns_left == 0
    assert st.pending_order is None


def test_active_buff_defaults() -> None:
    buff = ActiveBuff(
        id="mark_of_chaos",
        source_ability_id="mark_of_chaos",
        turns_remaining=3,
    )
    assert buff.data == {}
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_commander_entity.py -v
```

- [ ] **Step 3: Write commander module**

Create `src/spacefleet/commander/commander.py`:

```python
"""Commander entity — per-fleet owner of active abilities + passive skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spacefleet.core.types import Faction
    from spacefleet.phases.command_phase import AbilityOrder


@dataclass
class AbilityState:
    """Per-ability runtime state — charges, cooldown, pending prep order."""

    remaining_charges: int
    cooldown_remaining: int = 0
    preparation_turns_left: int = 0
    pending_order: AbilityOrder | None = None


@dataclass
class ActiveBuff:
    """A timed effect created by a resolved ability.

    Ticked down at the top of each turn inside the command phase;
    dropped when ``turns_remaining`` hits 0.  Passive dispatcher
    consults ``data`` for per-buff parameters.
    """

    id: str
    source_ability_id: str
    turns_remaining: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Commander:
    """Per-fleet commander: level, loadout, runtime state."""

    id: str
    name: str
    faction: Faction
    level: int = 1
    xp: int = 0
    active_ability_ids: list[str] = field(default_factory=list)
    passive_skill_ids: list[str] = field(default_factory=list)
    trait_ids: list[str] = field(default_factory=list)
    ability_state: dict[str, AbilityState] = field(default_factory=dict)
    active_buffs: list[ActiveBuff] = field(default_factory=list)
```

- [ ] **Step 4: Run — pass**
- [ ] **Step 5: Full gate + commit**

```bash
git add src/spacefleet/commander/commander.py tests/test_commander_entity.py
git commit -m "feat(commander): Commander entity + AbilityState + ActiveBuff"
```

---

## Task 4: Ship.battles_survived + crew_tier

**Files:**
- Modify: `src/spacefleet/models/ship.py`
- Create: `tests/test_ship_crew_tier.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_ship_crew_tier.py`:

```python
"""Ship carries per-instance crew veterancy."""

from __future__ import annotations

from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        "s1", "Test", HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )


def test_ship_battles_survived_defaults_zero() -> None:
    assert _ship().battles_survived == 0


def test_ship_crew_tier_derived() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    s = _ship()
    assert s.crew_tier == 0

    s.battles_survived = 2
    assert s.crew_tier == 1

    s.battles_survived = 10
    assert s.crew_tier == 3
```

- [ ] **Step 2: Run — expect attribute error**

- [ ] **Step 3: Add field + property to Ship**

Modify `src/spacefleet/models/ship.py`. Locate the field block (around line 72, after `crit_temporary_repairs`) and add:

```python
    # ── crew veterancy ──
    battles_survived: int = 0
```

Then add a property (below `effective_leadership`, around line 174):

```python
    @property
    def crew_tier(self) -> int:
        """Per-ship crew veterancy tier, derived from ``battles_survived``."""
        from spacefleet.commander.progression import crew_tier_for  # local import

        return crew_tier_for(self.battles_survived)
```

- [ ] **Step 4: Run — pass**
- [ ] **Step 5: Full gate + commit**

```bash
git add src/spacefleet/models/ship.py tests/test_ship_crew_tier.py
git commit -m "feat(ship): battles_survived field + derived crew_tier property"
```

---

## Task 5: Fleet extensions

**Files:**
- Modify: `src/spacefleet/models/fleet.py`
- Create: `tests/test_fleet_commander_integration.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_fleet_commander_integration.py`:

```python
"""Fleet holds commander + flagship + ship ids, resolves against state."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def _make_ship(sid: str) -> Ship:
    return Ship.from_profile(
        sid, sid, HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )


def test_fleet_holds_commander_and_flagship() -> None:
    cmdr = Commander(id="c1", name="Admiral", faction=Faction.IMPERIAL_NAVY)
    fleet = Fleet(
        id="player1",
        commander=cmdr,
        flagship_ship_id="ship_a",
        ship_ids=["ship_a", "ship_b"],
    )
    assert fleet.id == "player1"
    assert fleet.commander is cmdr
    assert fleet.flagship_ship_id == "ship_a"


def test_ships_in_resolves_against_state() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    b = _make_ship("ship_b")
    state.add_ship(a)
    state.add_ship(b)
    fleet = Fleet(id="f", ship_ids=["ship_a", "ship_b", "missing"])
    resolved = fleet.ships_in(state)
    assert len(resolved) == 2
    assert a in resolved
    assert b in resolved


def test_alive_ships_in_filters_destroyed() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    b = _make_ship("ship_b")
    b.is_destroyed = True
    state.add_ship(a)
    state.add_ship(b)
    fleet = Fleet(id="f", ship_ids=["ship_a", "ship_b"])
    assert fleet.alive_ships_in(state) == [a]


def test_flagship_in_returns_none_when_down() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    a.is_destroyed = True
    state.add_ship(a)
    fleet = Fleet(id="f", flagship_ship_id="ship_a", ship_ids=["ship_a"])
    assert fleet.flagship_in(state) is None


def test_flagship_in_returns_ship_when_alive() -> None:
    state = CoreGameState()
    a = _make_ship("ship_a")
    state.add_ship(a)
    fleet = Fleet(id="f", flagship_ship_id="ship_a", ship_ids=["ship_a"])
    assert fleet.flagship_in(state) is a
```

- [ ] **Step 2: Run — expect failures on unknown fields**

- [ ] **Step 3: Extend Fleet**

Rewrite `src/spacefleet/models/fleet.py`:

```python
"""Fleet container — ships under one commander's control."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from spacefleet.commander.commander import Commander
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Faction
    from spacefleet.models.ship import Ship


@dataclass
class Fleet:
    """A fleet identified by ``id`` (player_id for humans, ``ai_<n>`` for AI).

    Holds the commander (optional — AI hulks have none), the flagship
    ship id, and the list of ship ids that make up the fleet.  Ships
    themselves live in :class:`CoreGameState.ships`; this fleet
    resolves them on demand via ``ships_in``.
    """

    id: str = ""
    commander: Commander | None = None
    flagship_ship_id: str | None = None
    ship_ids: list[str] = field(default_factory=list)
    # Legacy fields (kept for back-compat with Fleet.total_hull_points()):
    commander_name: str = ""
    ships: list[Ship] = field(default_factory=list)

    # ── New accessors (state-aware) ───────────────────────

    def ships_in(self, state: CoreGameState) -> list[Ship]:
        return [state.ships[sid] for sid in self.ship_ids if sid in state.ships]

    def alive_ships_in(self, state: CoreGameState) -> list[Ship]:
        return [s for s in self.ships_in(state) if s.alive]

    def flagship_in(self, state: CoreGameState) -> Ship | None:
        if self.flagship_ship_id is None:
            return None
        ship = state.ships.get(self.flagship_ship_id)
        return ship if (ship is not None and ship.alive) else None

    # ── Legacy passthroughs (unchanged) ───────────────────

    def add(self, ship: Ship) -> None:
        self.ships.append(ship)

    def remove(self, ship_id: str) -> None:
        self.ships = [s for s in self.ships if s.id != ship_id]

    def alive(self) -> list[Ship]:
        return [s for s in self.ships if s.alive]

    def total_hull_points(self) -> int:
        return sum(s.hull_current for s in self.ships)

    @property
    def faction(self) -> Faction | None:
        return self.ships[0].faction if self.ships else None

    def __iter__(self) -> Iterator[Ship]:
        return iter(self.ships)

    def __len__(self) -> int:
        return len(self.ships)
```

- [ ] **Step 4: Run — pass. Verify existing Fleet tests still pass.**
- [ ] **Step 5: Full gate + commit**

```bash
git add src/spacefleet/models/fleet.py tests/test_fleet_commander_integration.py
git commit -m "feat(fleet): add commander + flagship_ship_id + ship_ids + state-aware accessors"
```

---

## Task 6: CoreGameState.fleets + fleet_of

**Files:**
- Modify: `src/spacefleet/core/game_state.py`
- Create: `tests/test_game_state_fleets.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_game_state_fleets.py`:

```python
"""CoreGameState holds fleets and looks up the fleet of a ship."""

from __future__ import annotations

from spacefleet.core.game_state import CoreGameState
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def _ship(sid: str) -> Ship:
    return Ship.from_profile(
        sid, sid, HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )


def test_fleets_default_empty() -> None:
    state = CoreGameState()
    assert state.fleets == {}


def test_fleet_of_ship() -> None:
    state = CoreGameState()
    a = _ship("a")
    b = _ship("b")
    state.add_ship(a)
    state.add_ship(b)
    fleet = Fleet(id="f1", ship_ids=["a", "b"])
    state.fleets["f1"] = fleet
    assert state.fleet_of(a) is fleet
    assert state.fleet_of(b) is fleet


def test_fleet_of_unlisted_ship_is_none() -> None:
    state = CoreGameState()
    a = _ship("a")
    state.add_ship(a)
    assert state.fleet_of(a) is None
```

- [ ] **Step 2: Add to CoreGameState**

Modify `src/spacefleet/core/game_state.py`. Add to imports:

```python
if TYPE_CHECKING:
    from spacefleet.core.types import Faction
    from spacefleet.models.fleet import Fleet
    from spacefleet.models.ship import Ship
```

Add field and method:

```python
    # within @dataclass CoreGameState, after `events: EventBus = field(...)`:
    fleets: dict[str, Fleet] = field(default_factory=dict)

    def fleet_of(self, ship: Ship) -> Fleet | None:
        for fleet in self.fleets.values():
            if ship.id in fleet.ship_ids:
                return fleet
        return None
```

- [ ] **Step 3: Run — pass**
- [ ] **Step 4: Full gate + commit**

```bash
git add src/spacefleet/core/game_state.py tests/test_game_state_fleets.py
git commit -m "feat(core): CoreGameState.fleets + fleet_of(ship) helper"
```

---

## Task 7: Effect step dataclasses

Define all twelve effect-step tagged-union dataclasses. No resolvers yet (those come in Tasks 12–17).

**Files:**
- Modify: `src/spacefleet/commander/abilities.py`
- Create: `tests/test_effect_steps_construction.py`

- [ ] **Step 1: Write failing construction test**

Create `tests/test_effect_steps_construction.py`:

```python
"""All twelve effect-step dataclasses construct cleanly."""

from __future__ import annotations

from spacefleet.commander.abilities import (
    AreaHullDamage,
    AreaMoraleDamage,
    AreaMoraleRestore,
    BonusBoardingAssault,
    BonusTorpedoSalvo,
    ConcentratedFireBuff,
    ExtinguishFires,
    HullRepair,
    RepairTempCritical,
    SpawnProbe,
    Teleport,
    TimedFleetBuff,
)


def test_all_steps_construct() -> None:
    HullRepair(amount_dice="D3")
    ExtinguishFires()
    RepairTempCritical(count=1)
    AreaMoraleRestore(range_gu=40.0, amount=30, cancel_mutiny=True)
    AreaHullDamage(range_gu=15.0, amount_dice="D3", affects_allies=True)
    AreaMoraleDamage(range_gu=15.0, amount=20, affects_allies=True)
    SpawnProbe(radius=30.0, duration=3, detection_level=3)
    ConcentratedFireBuff(range_gu=30.0, column_shift=1, duration=2)
    TimedFleetBuff(buff_id="mark_of_chaos", duration=3, data={"morale_immunity": True})
    BonusTorpedoSalvo(range_gu=50.0)
    Teleport()
    BonusBoardingAssault(actions=3, extended_range_gu=15.0)
```

- [ ] **Step 2: Replace abilities.py with full step definitions**

Overwrite `src/spacefleet/commander/abilities.py`:

```python
"""Commander active abilities — declarative effect-step primitives.

Each ``AbilityDef`` carries a tuple of effect steps (tagged union).
``resolve_ability`` (Task 18) walks the steps in order, dispatching
each through a handler registry.  Events produced by the resolver are
returned to the caller (``resolve_command_phase``) for logging /
publication on the ``EventBus``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Effect steps ──────────────────────────────────────────


@dataclass(frozen=True)
class HullRepair:
    amount_dice: str  # "D3" | "D6"


@dataclass(frozen=True)
class ExtinguishFires:
    pass


@dataclass(frozen=True)
class RepairTempCritical:
    count: int


@dataclass(frozen=True)
class AreaMoraleRestore:
    range_gu: float
    amount: int
    cancel_mutiny: bool


@dataclass(frozen=True)
class AreaHullDamage:
    range_gu: float
    amount_dice: str
    affects_allies: bool


@dataclass(frozen=True)
class AreaMoraleDamage:
    range_gu: float
    amount: int
    affects_allies: bool


@dataclass(frozen=True)
class SpawnProbe:
    radius: float
    duration: int
    detection_level: int


@dataclass(frozen=True)
class ConcentratedFireBuff:
    range_gu: float
    column_shift: int
    duration: int


@dataclass(frozen=True)
class TimedFleetBuff:
    buff_id: str
    duration: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BonusTorpedoSalvo:
    range_gu: float


@dataclass(frozen=True)
class Teleport:
    pass


@dataclass(frozen=True)
class BonusBoardingAssault:
    actions: int
    extended_range_gu: float


EffectStep = (
    HullRepair
    | ExtinguishFires
    | RepairTempCritical
    | AreaMoraleRestore
    | AreaHullDamage
    | AreaMoraleDamage
    | SpawnProbe
    | ConcentratedFireBuff
    | TimedFleetBuff
    | BonusTorpedoSalvo
    | Teleport
    | BonusBoardingAssault
)


# ── AbilityDef ────────────────────────────────────────────


@dataclass(frozen=True)
class AbilityDef:
    id: str
    name: str
    category: str
    cooldown: int
    charges: int
    preparation_turns: int = 0
    range_gu: float | None = None
    faction: str | None = None
    sprint6_dependency: bool = False
    steps: tuple[EffectStep, ...] = ()
    raw_effects: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 3: Run — pass**
- [ ] **Step 4: Full gate + commit**

```bash
git add src/spacefleet/commander/abilities.py tests/test_effect_steps_construction.py
git commit -m "feat(commander): effect-step primitives (12 tagged-union dataclasses)"
```

---

## Task 8: Yaml → EffectStep parser

Fill in `SkillRegistry._parse_active` so `AbilityDef.steps` tuples populate from raw yaml effects.

**Files:**
- Modify: `src/spacefleet/data/skill_registry.py`
- Create: `tests/test_skill_registry_effect_steps.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_skill_registry_effect_steps.py`:

```python
"""Registry parses yaml effects into EffectStep tuples."""

from __future__ import annotations

from spacefleet.commander.abilities import (
    AreaHullDamage,
    AreaMoraleDamage,
    AreaMoraleRestore,
    BonusBoardingAssault,
    BonusTorpedoSalvo,
    ConcentratedFireBuff,
    ExtinguishFires,
    HullRepair,
    RepairTempCritical,
    SpawnProbe,
    Teleport,
    TimedFleetBuff,
)
from spacefleet.data.skill_registry import SkillRegistry


def _reload() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()


def test_emergency_repairs_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("emergency_repairs")
    assert a is not None
    kinds = [type(s) for s in a.steps]
    assert HullRepair in kinds
    assert ExtinguishFires in kinds
    assert RepairTempCritical in kinds


def test_call_to_arms_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("call_to_arms")
    assert a is not None
    assert any(isinstance(s, AreaMoraleRestore) and s.cancel_mutiny for s in a.steps)


def test_warp_rift_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("warp_rift")
    assert a is not None
    assert any(isinstance(s, AreaHullDamage) and s.affects_allies for s in a.steps)
    assert any(isinstance(s, AreaMoraleDamage) and s.affects_allies for s in a.steps)


def test_mark_of_chaos_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("mark_of_chaos")
    assert a is not None
    buffs = [s for s in a.steps if isinstance(s, TimedFleetBuff)]
    assert len(buffs) == 1
    assert buffs[0].data.get("morale_immunity") is True


def test_concentrated_fire_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("concentrated_fire")
    assert a is not None
    buff = next(s for s in a.steps if isinstance(s, ConcentratedFireBuff))
    assert buff.column_shift == 1
    assert buff.range_gu == 30.0


def test_micro_warp_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("micro_warp_jump")
    assert a is not None
    assert any(isinstance(s, Teleport) for s in a.steps)
    assert a.preparation_turns == 1


def test_torpedo_barrage_stub() -> None:
    _reload()
    a = SkillRegistry.get_active("torpedo_barrage")
    assert a is not None
    assert a.sprint6_dependency is True
    assert any(isinstance(s, BonusTorpedoSalvo) for s in a.steps)


def test_augur_probe_stub() -> None:
    _reload()
    a = SkillRegistry.get_active("augur_probe")
    assert a is not None
    assert a.sprint6_dependency is True
    assert any(isinstance(s, SpawnProbe) for s in a.steps)


def test_boarding_assault_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("boarding_assault")
    assert a is not None
    assert any(isinstance(s, BonusBoardingAssault) for s in a.steps)
```

- [ ] **Step 2: Extend `_parse_active` to emit steps**

Modify `src/spacefleet/data/skill_registry.py`. Replace the existing `_parse_active` with:

```python
    @classmethod
    def _parse_active(cls, aid: str, raw: dict[str, Any]) -> AbilityDef:
        from spacefleet.commander.abilities import (
            AbilityDef,
            AreaHullDamage,
            AreaMoraleDamage,
            AreaMoraleRestore,
            BonusBoardingAssault,
            BonusTorpedoSalvo,
            ConcentratedFireBuff,
            EffectStep,
            ExtinguishFires,
            HullRepair,
            RepairTempCritical,
            SpawnProbe,
            Teleport,
            TimedFleetBuff,
        )

        effects = dict(raw.get("effects") or {})
        is_sprint6 = bool(_SPRINT6_ABILITY_KEYS & effects.keys())
        range_gu = float(raw["range"]) if "range" in raw else None
        prep = int(raw.get("preparation_turns", 0))

        steps: list[EffectStep] = []

        # Hull repair family
        if "hull_restore" in effects:
            steps.append(HullRepair(amount_dice=str(effects["hull_restore"])))
        if effects.get("extinguish_fires") is True:
            steps.append(ExtinguishFires())
        if "repair_temp_crit" in effects:
            steps.append(RepairTempCritical(count=int(effects["repair_temp_crit"])))

        # Morale / AoE damage
        if "morale_restore" in effects:
            steps.append(
                AreaMoraleRestore(
                    range_gu=range_gu or 0.0,
                    amount=int(effects["morale_restore"]),
                    cancel_mutiny=bool(effects.get("cancel_mutiny", False)),
                )
            )
        if "area_damage" in effects:
            steps.append(
                AreaHullDamage(
                    range_gu=float(effects.get("area_radius", range_gu or 0.0)),
                    amount_dice=str(effects["area_damage"]),
                    affects_allies=bool(effects.get("affects_allies", False)),
                )
            )
        if "morale_damage" in effects:
            steps.append(
                AreaMoraleDamage(
                    range_gu=float(effects.get("area_radius", range_gu or 0.0)),
                    amount=int(effects["morale_damage"]),
                    affects_allies=bool(effects.get("affects_allies", False)),
                )
            )

        # Buffs
        if "gunnery_column_shift" in effects:
            steps.append(
                ConcentratedFireBuff(
                    range_gu=range_gu or 30.0,
                    column_shift=int(effects["gunnery_column_shift"]),
                    duration=int(effects.get("duration", 1)),
                )
            )
        if "lance_strength_bonus" in effects or "morale_immunity" in effects:
            data: dict[str, Any] = {}
            if "lance_strength_bonus" in effects:
                data["lance_strength_bonus"] = int(effects["lance_strength_bonus"])
            if "morale_immunity" in effects:
                data["morale_immunity"] = bool(effects["morale_immunity"])
            steps.append(
                TimedFleetBuff(
                    buff_id=aid,
                    duration=int(effects.get("duration", 1)),
                    data=data,
                )
            )

        # Sprint 6 stubs
        if "bonus_torpedo_salvo" in effects:
            steps.append(BonusTorpedoSalvo(range_gu=range_gu or 0.0))
        if "probe_radius" in effects:
            steps.append(
                SpawnProbe(
                    radius=float(effects["probe_radius"]),
                    duration=int(effects.get("probe_duration", 0)),
                    detection_level=int(effects.get("detection_level", 0)),
                )
            )

        # Boarding
        if "assault_actions" in effects:
            steps.append(
                BonusBoardingAssault(
                    actions=int(effects["assault_actions"]),
                    extended_range_gu=range_gu or 5.0,
                )
            )

        # Micro-warp — no "effects" dict, detected by preparation_turns + category
        if prep > 0 and not steps and aid == "micro_warp_jump":
            steps.append(Teleport())

        return AbilityDef(
            id=aid,
            name=str(raw.get("name", aid)),
            category=str(raw.get("category", "universal")),
            cooldown=int(raw.get("cooldown", 0)),
            charges=int(raw.get("charges", 1)),
            preparation_turns=prep,
            range_gu=range_gu,
            faction=str(raw.get("faction")) if raw.get("faction") else None,
            sprint6_dependency=is_sprint6,
            steps=tuple(steps),
            raw_effects=effects,
        )
```

Also update the fallback actives (`_load_fallback_actives`) — `steps=()` stays fine for fallback, only the yaml path populates steps. Tests that depend on steps use yaml.

- [ ] **Step 3: Run — pass**
- [ ] **Step 4: Full gate + commit**

```bash
git add src/spacefleet/data/skill_registry.py tests/test_skill_registry_effect_steps.py
git commit -m "feat(registry): parse yaml effects into EffectStep tuples"
```

---

## Remaining tasks (condensed — each follows the same red→green→refactor→commit cadence)

The tasks below reuse the same test/implementation pattern established in Tasks 1–8. Each listing gives the new files, the test skeleton, the implementation outline, and the commit message. Expand steps into full TDD micro-steps when implementing (failing-test commit-point → impl commit-point optional; single atomic commit per task is acceptable when all work is cohesive).

---

## Task 9: AbilityOrder dataclass

**Files:**
- Modify: `src/spacefleet/net/commands.py`
- Create: `tests/test_ability_order.py`

Test:

```python
from spacefleet.core.types import Vector2D
from spacefleet.net.commands import AbilityOrder


def test_ability_order_defaults() -> None:
    o = AbilityOrder(fleet_id="p1", ability_id="call_to_arms")
    assert o.target_ship_id is None
    assert o.target_position is None


def test_ability_order_with_target_ship() -> None:
    o = AbilityOrder(
        fleet_id="p1",
        ability_id="concentrated_fire",
        target_ship_id="enemy_1",
    )
    assert o.target_ship_id == "enemy_1"


def test_ability_order_with_position() -> None:
    o = AbilityOrder(
        fleet_id="p1",
        ability_id="warp_rift",
        target_position=Vector2D(10.0, 20.0),
    )
    assert o.target_position == Vector2D(10.0, 20.0)
```

Implementation — append to `src/spacefleet/net/commands.py`:

```python
from spacefleet.core.types import Vector2D


@dataclass
class AbilityOrder:
    """A commander ability invocation.

    Separate from :class:`Command` — rides its own channel to
    ``resolve_turn`` and does not replace a ship's move/fire order.
    """

    fleet_id: str
    ability_id: str
    target_ship_id: str | None = None
    target_position: Vector2D | None = None
```

Commit: `feat(net): AbilityOrder dataclass for commander ability channel`

---

## Task 10: PassiveHook enum + PassiveContext + PassiveBus skeleton

**Files:**
- Create: `src/spacefleet/commander/passive_skills.py`
- Create: `tests/test_passive_bus_dispatch.py`

Test:

```python
"""PassiveBus dispatch semantics: aggregation, overrides, default."""

from __future__ import annotations

from spacefleet.commander.passive_skills import (
    PassiveBus,
    PassiveContext,
    PassiveHook,
)
from spacefleet.core.game_state import CoreGameState


def test_dispatch_with_no_handlers_returns_default() -> None:
    state = CoreGameState()
    bus = PassiveBus.build(state)
    ctx = PassiveContext(ship=None, fleet=None, state=state, value=0)
    result = bus.dispatch(PassiveHook.FLEET_SPEED_MAX, ctx)
    assert result == 0


def test_register_and_sum_contributions() -> None:
    state = CoreGameState()
    bus = PassiveBus.build(state)
    bus.register(
        source="test_a",
        hook=PassiveHook.FLEET_SPEED_MAX,
        handler=lambda ctx: ctx.value + 5,
    )
    bus.register(
        source="test_b",
        hook=PassiveHook.FLEET_SPEED_MAX,
        handler=lambda ctx: ctx.value + 3,
    )
    ctx = PassiveContext(ship=None, fleet=None, state=state, value=0)
    assert bus.dispatch(PassiveHook.FLEET_SPEED_MAX, ctx) == 8


def test_override_hook_first_writer_wins() -> None:
    """LANCE_HIT_THRESHOLD override semantics: first handler with non-None wins."""
    state = CoreGameState()
    bus = PassiveBus.build(state)
    bus.register(
        source="a",
        hook=PassiveHook.LANCE_HIT_THRESHOLD,
        handler=lambda ctx: 3,
    )
    bus.register(
        source="b",
        hook=PassiveHook.LANCE_HIT_THRESHOLD,
        handler=lambda ctx: 2,
    )
    ctx = PassiveContext(ship=None, fleet=None, state=state, value=None)
    assert bus.dispatch(PassiveHook.LANCE_HIT_THRESHOLD, ctx) == 3
```

Implementation:

```python
"""PassiveBus — named-hook dispatcher for passive skill effects.

Built once per turn from state.fleets + state.ships.  Handlers contribute
to one of two hook kinds:

* **Aggregate** (default) — each handler receives ``ctx.value``, returns
  a modified value; results chain through all handlers.  Used for sums
  (speed bonus) or multipliers (morale loss reduction).
* **Override** — first handler returning a non-``None`` value wins.
  Used for threshold rules (``LANCE_HIT_THRESHOLD``,
  ``ANTI_MUTINY_CHECK``).

The distinction is made by the caller: aggregate dispatch passes a
starting ``ctx.value`` and returns the chained result; override
dispatch passes ``value=None`` and returns the first non-None.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.models.fleet import Fleet
    from spacefleet.models.ship import Ship


class PassiveHook(StrEnum):
    FLEET_SPEED_MAX = "fleet_speed_max"
    FLEET_SENSOR_RANGE = "fleet_sensor_range"
    FLEET_ARMOR_PROW = "fleet_armor_prow"
    BATTERY_FIREPOWER_BONUS = "battery_firepower_bonus"
    AHEAD_FULL_DICE = "ahead_full_dice"
    HIT_COLUMN_SHIFT = "hit_column_shift"
    LANCE_HIT_THRESHOLD = "lance_hit_threshold"
    END_OF_TURN_SHIELD_REGEN = "end_of_turn_shield_regen"
    END_OF_TURN_HULL_REGEN = "end_of_turn_hull_regen"
    MORALE_LOSS_APPLY = "morale_loss_apply"
    MORALE_STARTING_BONUS = "morale_starting_bonus"
    HULL_BREACH_APPLY = "hull_breach_apply"
    ANTI_MUTINY_CHECK = "anti_mutiny_check"
    ABILITY_COOLDOWN_REDUCTION = "ability_cooldown_reduction"
    # Sprint 6-dependent (accepted but never dispatched yet)
    TORPEDO_SPEED_MULT = "torpedo_speed_mult"
    TORPEDO_RELOAD_REDUCTION = "torpedo_reload_reduction"
    TORPEDO_STRENGTH = "torpedo_strength"


@dataclass
class PassiveContext:
    ship: Ship | None
    fleet: Fleet | None
    state: CoreGameState
    value: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[PassiveContext], Any]


class PassiveBus:
    """Per-turn dispatcher.  Rebuilt after the command phase to pick up buffs."""

    def __init__(self) -> None:
        self._handlers: dict[PassiveHook, list[tuple[str, Handler]]] = {}

    def register(self, *, source: str, hook: PassiveHook, handler: Handler) -> None:
        self._handlers.setdefault(hook, []).append((source, handler))

    def dispatch(self, hook: PassiveHook, ctx: PassiveContext) -> Any:
        """Aggregate if ``ctx.value`` is not None; override otherwise."""
        handlers = self._handlers.get(hook, [])
        if ctx.value is None:
            for _src, fn in handlers:
                result = fn(ctx)
                if result is not None:
                    return result
            return None
        value = ctx.value
        for _src, fn in handlers:
            ctx.value = value
            value = fn(ctx)
        return value

    @classmethod
    def build(cls, state: CoreGameState) -> PassiveBus:
        """Build a bus from the state's fleets + ships.

        Handler registration for each passive_id / buff_id / crew_tier
        is delegated to :func:`spacefleet.commander.passive_skills.register_all`
        (added in later tasks).  For the skeleton task this returns an
        empty bus; later tasks layer handlers on.
        """
        bus = cls()
        # Handler registration added in Tasks 22 (universal), 23 (faction), 29 (crew tier).
        return bus
```

Commit: `feat(commander): PassiveBus skeleton + PassiveHook enum + PassiveContext`

---

## Task 11: Morale-loss passive hook + `apply_morale_change(delta, state=None)` + `veteran_crews` + `mark_of_chaos` immunity

**Files:**
- Modify: `src/spacefleet/models/ship.py` — extend `apply_morale_change`
- Modify: `src/spacefleet/commander/passive_skills.py` — add `register_morale_loss_handlers(bus, state)`
- Modify: `src/spacefleet/combat/morale_effects.py` — pass `state` through
- Create: `tests/test_passive_veteran_crews.py`
- Create: `tests/test_passive_mark_of_chaos_immunity.py`

Test (veteran_crews):

```python
"""veteran_crews reduces morale loss by 25%."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def test_morale_loss_reduced_by_veteran_crews() -> None:
    state = CoreGameState()
    ship = Ship.from_profile(
        "s1", "Ship", HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )
    state.add_ship(ship)
    cmdr = Commander(
        id="c1", name="Adm", faction=Faction.CHAOS_FLEET,
        passive_skill_ids=["veteran_crews"],
    )
    state.fleets["f1"] = Fleet(
        id="f1", commander=cmdr, ship_ids=["s1"], flagship_ship_id="s1",
    )

    from spacefleet.commander.passive_skills import PassiveBus
    state.passives = PassiveBus.build(state)  # registrations pull veteran_crews in

    before = ship.morale
    ship.apply_morale_change(-20, state=state)
    # 20 * 0.75 = 15 loss
    assert before - ship.morale == 15


def test_morale_loss_raw_when_no_state() -> None:
    ship = Ship.from_profile(
        "s1", "Ship", HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )
    before = ship.morale
    ship.apply_morale_change(-20)  # no state kwarg
    assert before - ship.morale == 20
```

Test (mark_of_chaos immunity):

```python
"""mark_of_chaos buff blocks morale loss on buffed flagship."""

from __future__ import annotations

from spacefleet.commander.commander import ActiveBuff, Commander
from spacefleet.commander.passive_skills import PassiveBus
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def test_mark_of_chaos_blocks_morale_loss_on_flagship() -> None:
    state = CoreGameState()
    ship = Ship.from_profile(
        "flag", "Flag", HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )
    state.add_ship(ship)
    cmdr = Commander(id="c1", name="Adm", faction=Faction.CHAOS_FLEET)
    cmdr.active_buffs.append(
        ActiveBuff(
            id="mark_of_chaos",
            source_ability_id="mark_of_chaos",
            turns_remaining=3,
            data={"morale_immunity": True},
        )
    )
    state.fleets["f1"] = Fleet(
        id="f1", commander=cmdr, ship_ids=["flag"], flagship_ship_id="flag",
    )
    state.passives = PassiveBus.build(state)

    before = ship.morale
    ship.apply_morale_change(-20, state=state)
    assert ship.morale == before   # no loss
```

Implementation — modify `src/spacefleet/models/ship.py::apply_morale_change`:

```python
    def apply_morale_change(self, delta: int, *, state: CoreGameState | None = None) -> int:
        """Adjust morale clamped to [0, morale_max].  Returns actual change.

        When *state* is provided and *delta* < 0, routes the loss through
        ``PassiveHook.MORALE_LOSS_APPLY`` so passives can reduce or negate
        the loss.  Gains and no-state calls apply raw.
        """
        effective_delta = delta
        if state is not None and delta < 0:
            from spacefleet.commander.passive_skills import (
                PassiveContext,
                PassiveHook,
            )

            fleet = state.fleet_of(self)
            passives = getattr(state, "passives", None)
            if passives is not None:
                ctx = PassiveContext(ship=self, fleet=fleet, state=state, value=delta)
                result = passives.dispatch(PassiveHook.MORALE_LOSS_APPLY, ctx)
                effective_delta = int(result)
        before = self.morale
        self.morale = max(0, min(self.morale_max, self.morale + effective_delta))
        return self.morale - before
```

Add at top of `ship.py` (TYPE_CHECKING block):

```python
if TYPE_CHECKING:
    from spacefleet.core.game_state import CoreGameState
    # ... existing
```

Add to `src/spacefleet/commander/passive_skills.py` — a handler-registration helper and wire it from `PassiveBus.build`:

```python
def _register_morale_loss_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue
        if "veteran_crews" in cmdr.passive_skill_ids:
            bus.register(
                source=f"{fleet.id}:veteran_crews",
                hook=PassiveHook.MORALE_LOSS_APPLY,
                handler=lambda ctx, f=fleet: int(ctx.value * 0.75)
                if ctx.ship is not None and ctx.ship.id in f.ship_ids
                else ctx.value,
            )
        for buff in cmdr.active_buffs:
            if buff.data.get("morale_immunity"):
                flagship_id = fleet.flagship_ship_id
                bus.register(
                    source=f"{fleet.id}:{buff.id}:immunity",
                    hook=PassiveHook.MORALE_LOSS_APPLY,
                    handler=lambda ctx, fid=flagship_id: 0
                    if ctx.ship is not None and ctx.ship.id == fid
                    else ctx.value,
                )
```

Wire in `PassiveBus.build`:

```python
    @classmethod
    def build(cls, state: CoreGameState) -> PassiveBus:
        bus = cls()
        _register_morale_loss_handlers(bus, state)
        return bus
```

Modify `src/spacefleet/combat/morale_effects.py` — for every call to `ship.apply_morale_change(...)`, add `state=state` kwarg (wherever the function has a state param). If a helper lacks state param, add it (optional, default None). Example signature change:

```python
def apply_hull_damage_morale(
    ship: Ship, damage: int, *, state: CoreGameState | None = None,
) -> int:
    ...
    return ship.apply_morale_change(delta, state=state)
```

Callers of `apply_hull_damage_morale` (in `combat/resolution.py`, `combat/projectile_resolution.py`) now pass `state=state` — those call sites get the plumbing in Task 19 (turn_resolver threads state through).

Commit: `feat(commander): veteran_crews + mark_of_chaos morale-loss passive hook`

---

## Task 12: Speed passive hook + `swift_maneuvers` + movement_phase wiring

**Files:**
- Modify: `src/spacefleet/commander/passive_skills.py` — add `_register_speed_handlers`, add `effective_speed_max_with_passives`
- Modify: `src/spacefleet/phases/movement_phase.py` — use the helper for cap computation
- Create: `tests/test_passive_swift_maneuvers.py`

Test:

```python
"""swift_maneuvers adds +5 to fleet speed cap."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.commander.passive_skills import (
    PassiveBus,
    effective_speed_max_with_passives,
)
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def test_swift_maneuvers_adds_5_to_speed_max() -> None:
    state = CoreGameState()
    s = Ship.from_profile(
        "s1", "S", HULK_HULL, make_hulk_weapons(),
        position=None, heading=0.0,
    )
    state.add_ship(s)
    cmdr = Commander(
        id="c1", name="A", faction=Faction.IMPERIAL_NAVY,
        passive_skill_ids=["swift_maneuvers"],
    )
    state.fleets["f1"] = Fleet(
        id="f1", commander=cmdr, ship_ids=["s1"], flagship_ship_id="s1",
    )
    state.passives = PassiveBus.build(state)

    base = s.effective_speed_max
    with_bonus = effective_speed_max_with_passives(s, state)
    assert with_bonus - base == 5.0
```

Implementation — append to `passive_skills.py`:

```python
def _register_speed_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue
        if "swift_maneuvers" in cmdr.passive_skill_ids:
            bus.register(
                source=f"{fleet.id}:swift_maneuvers",
                hook=PassiveHook.FLEET_SPEED_MAX,
                handler=lambda ctx, f=fleet: ctx.value + 5.0
                if ctx.ship is not None and ctx.ship.id in f.ship_ids
                else ctx.value,
            )


def effective_speed_max_with_passives(ship: Ship, state: CoreGameState) -> float:
    passives = getattr(state, "passives", None)
    if passives is None:
        return ship.effective_speed_max
    ctx = PassiveContext(
        ship=ship, fleet=state.fleet_of(ship), state=state, value=ship.effective_speed_max,
    )
    return float(passives.dispatch(PassiveHook.FLEET_SPEED_MAX, ctx))
```

Update `PassiveBus.build`:

```python
    @classmethod
    def build(cls, state: CoreGameState) -> PassiveBus:
        bus = cls()
        _register_morale_loss_handlers(bus, state)
        _register_speed_handlers(bus, state)
        return bus
```

Modify `src/spacefleet/phases/movement_phase.py` — in the place the cap is computed (`ship.effective_speed_max`) replace with `effective_speed_max_with_passives(ship, state)` only when the resolver has state. If `resolve_movement_phase` doesn't currently take state, give it an optional kwarg `state: CoreGameState | None = None` and thread. Turn resolver passes state (already has it).

Commit: `feat(commander): swift_maneuvers fleet speed bonus wired through movement phase`

---

## Task 13: HullRepair / ExtinguishFires / RepairTempCritical resolvers

**Files:**
- Modify: `src/spacefleet/commander/abilities.py` — add `resolve_step`
- Create: `tests/test_effect_step_hull_repair.py`
- Create: `tests/test_effect_step_extinguish_fires.py`
- Create: `tests/test_effect_step_repair_temp_crit.py`

Each test sets up a flagship ship, runs `resolve_step(step, ctx)`, asserts mutation.

Implementation — append to `abilities.py`:

```python
from spacefleet.core.events import Event


@dataclass
class HullRepairedEvent(Event):
    ship_id: str
    amount: int


@dataclass
class FiresExtinguishedEvent(Event):
    ship_id: str
    count: int


@dataclass
class TemporaryCritsRepairedEvent(Event):
    ship_id: str
    count: int


@dataclass
class StepContext:
    """Context threaded into each effect-step resolver."""
    ability_id: str
    commander: Commander
    fleet: Fleet
    flagship: Ship
    state: CoreGameState
    order: AbilityOrder
    dice: DiceRoller


def _roll_dice_str(spec: str, dice: DiceRoller) -> int:
    spec = spec.strip().upper()
    if spec == "D3":
        return dice.d3()
    if spec == "D6":
        return dice.d6()
    raise ValueError(f"Unsupported dice spec: {spec}")


def resolve_step(step: EffectStep, ctx: StepContext) -> list[Event]:
    if isinstance(step, HullRepair):
        amount = _roll_dice_str(step.amount_dice, ctx.dice)
        applied = min(amount, ctx.flagship.hull.hull_hits - ctx.flagship.hull_current)
        ctx.flagship.hull_current += applied
        return [HullRepairedEvent(ship_id=ctx.flagship.id, amount=applied)]
    if isinstance(step, ExtinguishFires):
        count = ctx.flagship.fires
        ctx.flagship.fires = 0
        return [FiresExtinguishedEvent(ship_id=ctx.flagship.id, count=count)]
    if isinstance(step, RepairTempCritical):
        n = min(step.count, len(ctx.flagship.crit_temporary_repairs))
        for _ in range(n):
            ctx.flagship.crit_temporary_repairs.pop()
        return [TemporaryCritsRepairedEvent(ship_id=ctx.flagship.id, count=n)]
    # Other step kinds handled in Tasks 14–17
    return []
```

Commit: `feat(abilities): resolve HullRepair / ExtinguishFires / RepairTempCritical steps`

---

## Task 14: AreaMoraleRestore + AreaMoraleDamage + AreaHullDamage resolvers

Adds to `resolve_step` inside `abilities.py`. Area hull damage routes through `apply_damage_pipeline` (shields absorb first).

Tests exercise:
- Morale restore within range and cancel_mutiny behavior
- Morale damage through `MORALE_LOSS_APPLY` hook (so `veteran_crews` still reduces)
- AoE hull damage through `apply_damage_pipeline`: shields absorb first, hull damage only on overflow
- `affects_allies=True` hits allies when flagged

Implementation additions to `resolve_step`:

```python
    if isinstance(step, AreaMoraleRestore):
        events: list[Event] = []
        for target in _ships_in_radius(ctx.state, ctx.flagship.position, step.range_gu,
                                       faction=ctx.flagship.faction, include_self=True):
            changed = target.apply_morale_change(step.amount, state=ctx.state)
            if changed:
                events.append(AreaMoraleRestoreHitEvent(
                    ship_id=target.id, amount=changed,
                ))
            if step.cancel_mutiny and target.morale > 0:
                # already restored above; mutiny gate clears naturally
                pass
        return events

    if isinstance(step, AreaMoraleDamage):
        events = []
        for target in _ships_in_radius(
            ctx.state, _order_center(ctx), step.range_gu,
            faction=None if step.affects_allies else _opposite_faction(ctx.flagship.faction),
            include_self=step.affects_allies,
        ):
            if not step.affects_allies and target.faction == ctx.flagship.faction:
                continue
            changed = target.apply_morale_change(-step.amount, state=ctx.state)
            if changed:
                events.append(AreaMoraleHitEvent(ship_id=target.id, amount=changed))
        return events

    if isinstance(step, AreaHullDamage):
        events = []
        amount = _roll_dice_str(step.amount_dice, ctx.dice)
        for target in _ships_in_radius(
            ctx.state, _order_center(ctx), step.range_gu,
            faction=None if step.affects_allies else _opposite_faction(ctx.flagship.faction),
            include_self=step.affects_allies,
        ):
            from spacefleet.combat.damage import apply_damage_pipeline
            report = apply_damage_pipeline(target, damage=amount, arc=None)
            # caller applies hull damage per existing pipeline contract
            if report.hull_damage > 0:
                target.take_hull_damage(report.hull_damage)
            events.append(AreaHullDamageHitEvent(
                ship_id=target.id, report=report,
            ))
        return events
```

Supporting helpers (add to abilities.py):

```python
def _ships_in_radius(
    state: CoreGameState, center, radius, *, faction, include_self: bool,
) -> list[Ship]:
    from spacefleet.spatial.geometry import distance
    out: list[Ship] = []
    for ship in state.alive_ships():
        if distance(center, ship.position) > radius:
            continue
        if faction is not None and ship.faction != faction:
            continue
        out.append(ship)
    return out


def _order_center(ctx: StepContext):
    if ctx.order.target_position is not None:
        return ctx.order.target_position
    return ctx.flagship.position


def _opposite_faction(f):
    from spacefleet.core.types import Faction
    return Faction.CHAOS_FLEET if f == Faction.IMPERIAL_NAVY else Faction.IMPERIAL_NAVY
```

Event types defined beside the others:

```python
@dataclass
class AreaMoraleRestoreHitEvent(Event):
    ship_id: str
    amount: int


@dataclass
class AreaMoraleHitEvent(Event):
    ship_id: str
    amount: int


@dataclass
class AreaHullDamageHitEvent(Event):
    ship_id: str
    report: Any  # DamageReport
```

Commit: `feat(abilities): AoE morale and hull damage steps (warp_rift, call_to_arms)`

---

## Task 15: ConcentratedFireBuff + TimedFleetBuff resolvers

Implementation additions:

```python
    if isinstance(step, ConcentratedFireBuff):
        target_id = ctx.order.target_ship_id
        if target_id is None:
            return []
        buff = ActiveBuff(
            id=f"concentrated_fire:{target_id}",
            source_ability_id=ctx.ability_id,
            turns_remaining=step.duration,
            data={
                "kind": "concentrated_fire",
                "target_ship_id": target_id,
                "range_gu": step.range_gu,
                "column_shift": step.column_shift,
            },
        )
        ctx.commander.active_buffs.append(buff)
        return [BuffAppliedEvent(fleet_id=ctx.fleet.id, buff_id=buff.id)]

    if isinstance(step, TimedFleetBuff):
        buff = ActiveBuff(
            id=step.buff_id,
            source_ability_id=ctx.ability_id,
            turns_remaining=step.duration,
            data=dict(step.data),
        )
        ctx.commander.active_buffs.append(buff)
        return [BuffAppliedEvent(fleet_id=ctx.fleet.id, buff_id=buff.id)]
```

Tests verify buff lands on `commander.active_buffs`, duration set correctly, re-build of PassiveBus after command phase picks up the buff.

Commit: `feat(abilities): ConcentratedFireBuff + TimedFleetBuff steps`

---

## Task 16: Teleport + BonusBoardingAssault

Teleport reads `ctx.order.target_position` and sets `ctx.flagship.position`.

BonusBoardingAssault resolves a bonus boarding action immediately with `ctx.order.target_ship_id` target, extended range gate. Uses existing `resolve_boarding` from `combat/boarding.py`.

Test: teleport moves flagship; boarding assault applies damage through boarding pipeline.

Commit: `feat(abilities): Teleport + BonusBoardingAssault steps`

---

## Task 17: Sprint 6 stubs (SpawnProbe + BonusTorpedoSalvo) + PendingSprint6Event

```python
@dataclass
class PendingSprint6Event(Event):
    ability_id: str
    note: str = ""


# in resolve_step:
    if isinstance(step, SpawnProbe):
        return [PendingSprint6Event(
            ability_id=ctx.ability_id,
            note="augur probe deployment pending Sprint 6 detection system",
        )]
    if isinstance(step, BonusTorpedoSalvo):
        return [PendingSprint6Event(
            ability_id=ctx.ability_id,
            note="torpedo barrage pending Sprint 6 torpedo system",
        )]
```

Tests assert event emitted, no state mutation.

Commit: `feat(abilities): Sprint 6 stubs (SpawnProbe, BonusTorpedoSalvo) + PendingSprint6Event`

---

## Task 18: resolve_ability dispatcher

Walks `AbilityDef.steps`, collecting events. Handles `sprint6_dependency` flag at entry (still runs steps — the steps themselves are stubs).

```python
def resolve_ability(
    *, ability_def: AbilityDef, ctx: StepContext,
) -> list[Event]:
    events: list[Event] = [AbilityUsedEvent(
        ability_id=ability_def.id, fleet_id=ctx.fleet.id,
    )]
    for step in ability_def.steps:
        events.extend(resolve_step(step, ctx))
    return events
```

`AbilityUsedEvent` defined in `phases/command_phase.py` (Task 19).

Test: calling `resolve_ability` with `emergency_repairs` mutates flagship hull/fires, emits correct events.

Commit: `feat(abilities): resolve_ability walks effect-step list`

---

## Task 19: resolve_command_phase — tick + validate + dispatch

**Files:**
- Create: `src/spacefleet/phases/command_phase.py`
- Create: `tests/test_command_phase_validation.py`
- Create: `tests/test_command_phase_cooldown_charges.py`

The module defines `AbilityOrder` already (imported from `net.commands` — or moved here? Spec says `net/commands.py`; keep import there and re-export from `command_phase`). Event types:

```python
@dataclass
class AbilityUsedEvent(TurnEvent): ability_id: str; fleet_id: str
@dataclass
class AbilityRejectedEvent(TurnEvent): ability_id: str; fleet_id: str; reason: str
@dataclass
class AbilityPrepStartedEvent(TurnEvent): ability_id: str; fleet_id: str; turns: int
@dataclass
class AbilityInterruptedEvent(TurnEvent): ability_id: str; fleet_id: str; reason: str
@dataclass
class BuffAppliedEvent(TurnEvent): fleet_id: str; buff_id: str
@dataclass
class BuffExpiredEvent(TurnEvent): fleet_id: str; buff_id: str
```

Where `TurnEvent` is the existing base in `net/turn_resolver.py`. **Decision:** move `TurnEvent` base to `core/events.py` (already a thin subclass of `Event`) and import from there, to avoid `phases/` → `net/` dependency cycle. Add to modify list.

```python
def resolve_command_phase(
    state: CoreGameState,
    ability_orders: dict[str, AbilityOrder],
    dice: DiceRoller,
) -> list[Event]:
    events: list[Event] = []

    # 1. Tick clocks for all commanders
    for fleet in state.fleets.values():
        cmdr = fleet.commander
        if cmdr is None:
            continue
        for st in cmdr.ability_state.values():
            if st.cooldown_remaining > 0:
                st.cooldown_remaining -= 1
            if st.pending_order is not None and st.preparation_turns_left > 0:
                st.preparation_turns_left -= 1
        # Tick buffs
        kept: list[ActiveBuff] = []
        for buff in cmdr.active_buffs:
            buff.turns_remaining -= 1
            if buff.turns_remaining > 0:
                kept.append(buff)
            else:
                events.append(BuffExpiredEvent(fleet_id=fleet.id, buff_id=buff.id))
        cmdr.active_buffs = kept

    # 2. Resolve any orders with completed prep first
    for fleet in sorted(state.fleets.values(), key=lambda f: f.id):
        cmdr = fleet.commander
        if cmdr is None:
            continue
        for aid, st in list(cmdr.ability_state.items()):
            if st.pending_order is not None and st.preparation_turns_left == 0:
                order = st.pending_order
                st.pending_order = None
                events.extend(_resolve_one(state, fleet, cmdr, aid, order, dice))

    # 3. Resolve incoming orders (sorted by fleet_id for determinism)
    for fleet_id in sorted(ability_orders.keys()):
        order = ability_orders[fleet_id]
        fleet = state.fleets.get(fleet_id)
        if fleet is None:
            events.append(AbilityRejectedEvent(
                ability_id=order.ability_id, fleet_id=fleet_id, reason="no_fleet",
            ))
            continue
        cmdr = fleet.commander
        if cmdr is None:
            events.append(AbilityRejectedEvent(
                ability_id=order.ability_id, fleet_id=fleet_id, reason="no_commander",
            ))
            continue
        # validate + prep gate + dispatch
        events.extend(_dispatch(state, fleet, cmdr, order, dice))

    return events


def _dispatch(state, fleet, cmdr, order, dice) -> list[Event]:
    ability_def = SkillRegistry.get_active(order.ability_id)
    events: list[Event] = []
    if ability_def is None:
        events.append(AbilityRejectedEvent(
            ability_id=order.ability_id, fleet_id=fleet.id, reason="not_owned",
        ))
        return events
    # Ownership
    if order.ability_id not in cmdr.active_ability_ids:
        events.append(AbilityRejectedEvent(
            ability_id=order.ability_id, fleet_id=fleet.id, reason="not_owned",
        ))
        return events
    # Faction
    if ability_def.faction is not None and cmdr.faction.value != ability_def.faction:
        events.append(AbilityRejectedEvent(
            ability_id=order.ability_id, fleet_id=fleet.id, reason="faction_mismatch",
        ))
        return events
    # Flagship alive
    flagship = fleet.flagship_in(state)
    if flagship is None:
        events.append(AbilityRejectedEvent(
            ability_id=order.ability_id, fleet_id=fleet.id, reason="flagship_down",
        ))
        return events
    # Ability state init on first use
    st = cmdr.ability_state.setdefault(
        order.ability_id, AbilityState(remaining_charges=ability_def.charges),
    )
    if st.remaining_charges <= 0:
        events.append(AbilityRejectedEvent(
            ability_id=order.ability_id, fleet_id=fleet.id, reason="no_charges",
        ))
        return events
    if st.cooldown_remaining > 0:
        events.append(AbilityRejectedEvent(
            ability_id=order.ability_id, fleet_id=fleet.id, reason="cooldown",
        ))
        return events
    # Target validation
    if order.target_ship_id is not None:
        target = state.ships.get(order.target_ship_id)
        if target is None or not target.alive:
            events.append(AbilityRejectedEvent(
                ability_id=order.ability_id, fleet_id=fleet.id, reason="target_missing",
            ))
            return events
        if ability_def.range_gu is not None:
            from spacefleet.spatial.geometry import distance
            if distance(flagship.position, target.position) > ability_def.range_gu:
                events.append(AbilityRejectedEvent(
                    ability_id=order.ability_id, fleet_id=fleet.id, reason="out_of_range",
                ))
                return events
    if order.target_position is not None and ability_def.range_gu is not None:
        from spacefleet.spatial.geometry import distance
        if distance(flagship.position, order.target_position) > ability_def.range_gu:
            events.append(AbilityRejectedEvent(
                ability_id=order.ability_id, fleet_id=fleet.id, reason="out_of_range",
            ))
            return events

    # Prep gate
    if ability_def.preparation_turns > 0 and st.pending_order is None:
        st.pending_order = order
        st.preparation_turns_left = ability_def.preparation_turns
        st.remaining_charges -= 1
        events.append(AbilityPrepStartedEvent(
            ability_id=order.ability_id, fleet_id=fleet.id,
            turns=ability_def.preparation_turns,
        ))
        return events

    events.extend(_resolve_one(state, fleet, cmdr, order.ability_id, order, dice))
    return events


def _resolve_one(state, fleet, cmdr, ability_id, order, dice) -> list[Event]:
    from spacefleet.commander.abilities import StepContext, resolve_ability
    ability_def = SkillRegistry.get_active(ability_id)
    assert ability_def is not None
    flagship = fleet.flagship_in(state)
    assert flagship is not None
    st = cmdr.ability_state.setdefault(
        ability_id, AbilityState(remaining_charges=ability_def.charges),
    )
    # Charge consumption: normal ability consumes on resolve;
    # prep-gated abilities already consumed at prep start.
    if ability_def.preparation_turns == 0:
        st.remaining_charges -= 1
    # Cooldown (with optional passive reduction — Task 29)
    st.cooldown_remaining = ability_def.cooldown

    ctx = StepContext(
        ability_id=ability_id,
        commander=cmdr,
        fleet=fleet,
        flagship=flagship,
        state=state,
        order=order,
        dice=dice,
    )
    return resolve_ability(ability_def=ability_def, ctx=ctx)
```

Tests verify: cooldown rejects second use, charges decrement, flagship_down rejects, faction mismatch, out-of-range.

Commit: `feat(phases): resolve_command_phase with validation + prep-gate`

---

## Task 20: Micro-warp prep/resolve + interruption

Uses the prep-gate logic already in Task 19. Interruption happens in the existing strike sub-phase (`net/turn_resolver.py`). When a boarding action lands on a flagship with a pending prep order, clear `pending_order`, restore charges, reset prep timer, emit `AbilityInterruptedEvent`.

Add to `turn_resolver.py` strike loop (after `apply_boarding_result`):

```python
# Check for prep interruption
fleet = state.fleet_of(target)
if fleet is not None and fleet.commander is not None:
    cmdr = fleet.commander
    if fleet.flagship_ship_id == target.id:
        for aid, st in list(cmdr.ability_state.items()):
            if st.pending_order is not None and st.preparation_turns_left > 0:
                st.pending_order = None
                st.preparation_turns_left = 0
                st.remaining_charges += 1
                emit(AbilityInterruptedEvent(
                    ability_id=aid, fleet_id=fleet.id, reason="boarding",
                ))
```

Test: prep on turn 1 → strike lands on flagship in turn 1 → order cleared, charges restored, event emitted.

Commit: `feat(phases): micro-warp prep interrupted by boarding actions`

---

## Task 21: Turn resolver signature + command phase wiring + PassiveBus build

**Files:**
- Modify: `src/spacefleet/net/turn_resolver.py` — `ability_orders` kwarg, call command phase first, `PassiveBus.build(state)` + rebuild after command phase
- Modify callers: `src/spacefleet/net/game_room.py` (or wherever `resolve_turn` is invoked — grep and add `ability_orders={}` default)

Change signature:

```python
def resolve_turn(
    state: GameState,
    commands: dict[str, Command],
    ability_orders: dict[str, AbilityOrder] | None = None,
) -> TurnLog:
    ...
    state.passives = PassiveBus.build(state)

    cmd_events = resolve_command_phase(state, ability_orders or {}, state.dice)
    for ev in cmd_events:
        emit(ev)

    # Rebuild to pick up buffs created in command phase
    state.passives = PassiveBus.build(state)

    # ... existing fire / movement / end-of-turn sub-phases ...
```

`state.passives` added dynamically — type it via `CoreGameState.passives: PassiveBus | None = None` field. Add to `core/game_state.py`.

Test: turn with one ability order runs command phase, emits AbilityUsedEvent alongside existing fire/move events.

Commit: `feat(net): turn_resolver wires command sub-phase + PassiveBus lifecycle`

---

## Task 22: Fire sub-phase hooks

Hook in `combat/resolution.py` and `combat/projectile_resolution.py`:

- Before `column_index(...)`, dispatch `HIT_COLUMN_SHIFT` with ctx carrying attacker + target + weapon; add the returned int to `stance_shift + aspect_shift`.
- Before `fp = ...`, dispatch `BATTERY_FIREPOWER_BONUS`; add to firepower (with range check for `master_gunner`).
- In `combat/lance.py` (or wherever lance hit threshold is applied), dispatch `LANCE_HIT_THRESHOLD` → if non-None, use as threshold.
- In `combat/critical_hits.py` Hull Breach path, check `HULL_BREACH_APPLY`; if False, skip extra damage.

Each of these functions gains `state: CoreGameState | None = None` kwarg. When None, no hook dispatch (pure unit-test path).

Tests:
- `test_passive_concentrated_fire_hit_count.py` — paint target, next turn fire produces +1 column result
- `test_passive_master_gunner_close_range.py` — close-range attack gets +1 firepower
- `test_passive_lance_mastery_threshold.py` — lance hits on 3+ when chaos commander holds lance_mastery
- `test_passive_reinforced_bulkheads.py` — hull breach does no extra damage

Register these handlers in `passive_skills.py` inside `PassiveBus.build` via a new `_register_combat_handlers(bus, state)`. Concentrated-fire buff handler walks `cmdr.active_buffs`.

Commit: `feat(combat): passive hooks for column shift, firepower, lance threshold, hull breach`

---

## Task 23: End-of-turn hooks

In `turn_resolver.py` end-of-turn loop:

```python
# Shield regen
extra_shields = state.passives.dispatch(
    PassiveHook.END_OF_TURN_SHIELD_REGEN,
    PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=0),
)
shields += int(extra_shields)
# Hull regen when crippled
if ship.hull_current < ship.hull.hull_hits * 0.5:
    extra_hull = state.passives.dispatch(
        PassiveHook.END_OF_TURN_HULL_REGEN,
        PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=0),
    )
    ship.hull_current = min(
        ship.hull.hull_hits, ship.hull_current + int(extra_hull),
    )
# Anti-mutiny
if ship.morale <= 0:
    suppressed = state.passives.dispatch(
        PassiveHook.ANTI_MUTINY_CHECK,
        PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=None),
    )
    if suppressed is True:
        ship.morale = 1  # suppressed
```

Register handlers for `shield_harmonics`, `dark_blessings`, `iron_discipline` in `passive_skills.py`.

Tests:
- `test_passive_shield_harmonics.py`
- `test_passive_dark_blessings_crippled.py`
- `test_passive_iron_discipline.py`

Commit: `feat(net): end-of-turn passive hooks (shield/hull regen, anti-mutiny)`

---

## Task 24: Universal passives batch

Register handlers for: `sensor_mastery` (FLEET_SENSOR_RANGE +20), `reinforced_bulkheads` (HULL_BREACH_APPLY = False), `master_gunner` (BATTERY_FIREPOWER_BONUS +1 at close range), `shield_harmonics` (END_OF_TURN_SHIELD_REGEN +1), `iron_discipline` (ANTI_MUTINY_CHECK → True when within 40 GU of flagship).

All in `passive_skills.py` inside new `_register_universal_passives(bus, state)`. Called from `PassiveBus.build`.

Also register Sprint 6-dep passives inertly (they register handlers but the hooks never fire): `short_burn_torpedoes` → TORPEDO_SPEED_MULT, `reload_drills` → TORPEDO_RELOAD_REDUCTION. Registration proves loadability.

Tests: one per universal passive (already outlined). Run as Task 24.

Commit: `feat(commander): register all universal passive-skill handlers`

---

## Task 25: Faction passives

`lance_mastery` (LANCE_HIT_THRESHOLD = 3), `prow_of_the_emperor` (FLEET_ARMOR_PROW +1), `dark_blessings` (END_OF_TURN_HULL_REGEN +1 when crippled), `speed_of_chaos` (AHEAD_FULL_DICE = 3), `boarding_expertise` (ASSAULT_ACTION_BONUS +1).

Tests: one per faction passive.

Commit: `feat(commander): register all faction passive-skill handlers`

---

## Task 26: Scenario auto-assignment

**Files:**
- Modify: `src/spacefleet/net/game_state.py`
- Create: `tests/test_default_commander_assignment.py`

Test:

```python
def test_pve_scenario_populates_fleets_with_commanders() -> None:
    state = GameState.create_pve(players=["p1"], ships_per_player=3, seed=1)
    assert "p1" in state.fleets
    fleet = state.fleets["p1"]
    assert fleet.commander is not None
    assert fleet.commander.level == 1
    assert fleet.flagship_ship_id is not None
    flagship = state.ships[fleet.flagship_ship_id]
    # Heaviest capital: Dauntless (light cruiser) beats Sword (escort)
    assert flagship.hull.classification.value == "light_cruiser"
    # Starter loadout: universal + faction
    assert "concentrated_fire" in fleet.commander.active_ability_ids
    assert fleet.commander.faction == Faction.IMPERIAL_NAVY


def test_ai_hulks_get_no_commander() -> None:
    state = GameState.create_pve(players=["p1"], ships_per_player=2, seed=1)
    # AI hulk fleets, if any, have commander=None
    for fleet_id, fleet in state.fleets.items():
        if fleet_id.startswith("ai_"):
            assert fleet.commander is None
```

Implementation in `net/game_state.py`:

```python
_CLASS_WEIGHT = {
    "battleship": 5,
    "battlecruiser": 4,
    "cruiser": 3,
    "light_cruiser": 2,
    "escort": 1,
}


def _class_weight(classification) -> int:
    return _CLASS_WEIGHT.get(classification.value, 0)


def _build_starter_commander(fleet_id: str, faction: Faction) -> Commander:
    from spacefleet.commander.commander import AbilityState, Commander
    from spacefleet.data.skill_registry import SkillRegistry

    active = ["concentrated_fire"]
    passive = ["veteran_crews"]
    if faction == Faction.IMPERIAL_NAVY:
        active.append("boarding_assault")
        passive.append("prow_of_the_emperor")
    elif faction == Faction.CHAOS_FLEET:
        active.append("mark_of_chaos")
        passive.append("lance_mastery")
    cmdr = Commander(
        id=f"{fleet_id}_cmdr",
        name=f"{fleet_id.title()} Commander",
        faction=faction,
        level=1,
        active_ability_ids=list(active),
        passive_skill_ids=list(passive),
    )
    for aid in active:
        d = SkillRegistry.get_active(aid)
        if d is not None:
            cmdr.ability_state[aid] = AbilityState(remaining_charges=d.charges)
    return cmdr


def _assign_default_commander(
    state: GameState, fleet_id: str, ship_ids: list[str], faction: Faction,
) -> None:
    if not ship_ids:
        return
    ships = [state.ships[sid] for sid in ship_ids]
    flagship = max(ships, key=lambda s: (_class_weight(s.hull.classification), s.id))
    cmdr = _build_starter_commander(fleet_id, faction)
    fleet = Fleet(
        id=fleet_id, commander=cmdr, flagship_ship_id=flagship.id,
        ship_ids=list(ship_ids), commander_name=cmdr.name, ships=list(ships),
    )
    state.fleets[fleet_id] = fleet
```

Call `_assign_default_commander(state, player_id, state.player_ships[player_id], Faction.IMPERIAL_NAVY)` at the end of each per-player loop inside `_add_imperial_fleet` and `_add_chaos_fleet`. For `_add_ai_hulks`, build a commander-less Fleet per group:

```python
fleet_id = f"ai_{len(state.ai_ships)}"
state.fleets[fleet_id] = Fleet(
    id=fleet_id, commander=None, flagship_ship_id=None,
    ship_ids=list(ai_batch_ids),
)
```

Also apply `MORALE_STARTING_BONUS` from crew tier at assignment (tier 0 = +0 so no-op at level 1; infrastructure for later).

Commit: `feat(net): auto-assign default commander to each fleet in scenarios`

---

## Task 27: Battle-end XP + crew veterancy

**Files:**
- Modify: `src/spacefleet/net/turn_resolver.py` — at end of `resolve_turn`, check `state.is_game_over()`, award XP + bump veterancy
- Create: `tests/test_battle_end_awards_xp.py`
- Create: `tests/test_battle_end_bumps_crew_veterancy.py`

Implementation at end of `resolve_turn`:

```python
if state.is_game_over():
    _award_battle_end(state, emit)

...

def _award_battle_end(state, emit):
    from spacefleet.commander.progression import (
        apply_xp, bump_crew_veterancy, compute_battle_xp_for_fleet,
    )

    alive_factions = {s.faction for s in state.ships.values() if s.alive}
    winning_faction = alive_factions.pop() if len(alive_factions) == 1 else None

    # First-blood credit: reconstruct from state.kills — earliest kill across fleets
    first_blood_fleet_id = _first_blood_fleet(state)

    for fleet_id, fleet in state.fleets.items():
        if fleet.commander is None:
            continue
        survived = bool(fleet.alive_ships_in(state))
        won = (
            winning_faction is not None
            and fleet.commander.faction == winning_faction
        )
        # Kill attribution: sum kills by owning player
        kill_count = state.kills.get(fleet_id, 0)
        # Classify from ShipClass — for Sprint 5 simplification, count all
        # kills as "escort" (safe lower bound) unless attacker-owned ship
        # records show capitals.  Classification enhancement deferred.
        capitals = 0
        escorts = kill_count
        xp = compute_battle_xp_for_fleet(
            fleet_kill_capitals=capitals,
            fleet_kill_escorts=escorts,
            won=won,
            survived=survived,
            first_blood=(fleet_id == first_blood_fleet_id),
        )
        for ev in apply_xp(fleet.commander, xp):
            emit(ev)
        for ship in fleet.alive_ships_in(state):
            for ev in bump_crew_veterancy(ship):
                emit(ev)


def _first_blood_fleet(state) -> str | None:
    # Simplified: fleet with >0 kills and lowest fleet_id.  Precise first-blood
    # tracking can be added when combat events are replayed post-battle.
    candidates = [fid for fid, n in state.kills.items() if n > 0]
    return min(candidates) if candidates else None
```

Tests verify XP gets awarded on game over, events fire, crew tier bumps for surviving ships. Accept simplified first-blood tracking for this sprint.

Commit: `feat(net): battle-end XP + crew veterancy award`

---

## Task 28: Crew tier → PassiveBus contributions

Register crew-tier handlers inside `PassiveBus.build` via `_register_crew_tier_handlers(bus, state)`:

- `HIT_COLUMN_SHIFT` contribution from `tier.accuracy_bonus` (rounded to int column shift — tier 3 accuracy 0.10 → 0, tier 4 accuracy 0.15 → 0; actually too small for column shift. Alternative: accumulate as `BATTERY_FIREPOWER_BONUS` via `tier.firepower_bonus` (tier 4 only — +1 firepower). Simplification: register only `BATTERY_FIREPOWER_BONUS` and `MORALE_STARTING_BONUS` and `ABILITY_COOLDOWN_REDUCTION` from tier.
- `MORALE_STARTING_BONUS` applied once at scenario setup (Task 26) — iterate ships, add `tier.morale_bonus` to `ship.morale` capped at `morale_max`.
- `ABILITY_COOLDOWN_REDUCTION` dispatched from `_resolve_one` when setting `cooldown_remaining`. Dispatch returns a multiplier ≤ 1.0; `cooldown_remaining = ceil(ability_def.cooldown * multiplier)`.

Update `_resolve_one` to use the reduction (edit Task 19 code):

```python
    from math import ceil
    cd = ability_def.cooldown
    mult = state.passives.dispatch(
        PassiveHook.ABILITY_COOLDOWN_REDUCTION,
        PassiveContext(ship=flagship, fleet=fleet, state=state, value=1.0),
    )
    st.cooldown_remaining = int(ceil(cd * mult))
```

Tests: tier 4 flagship fires an ability → cooldown reduced by 20%; tier 4 ship battery attack → firepower +1.

Commit: `feat(commander): crew-tier contributions to PassiveBus (firepower, cooldown, starting morale)`

---

## Task 29: CLI ability command

**Files:**
- Modify: `src/spacefleet/cli/game_cmd.py` — add `ability` parser
- Create: `tests/test_cli_ability_command.py`

Grammar:
```
ability <ability_id>
ability <ability_id> <target_ship_id>
ability <ability_id> at <x> <y>
```

Returns an `AbilityOrder`. Hooked into the CLI's per-turn order collection (parallel to existing ship-command collection). Status output adds `Commander: Lvl N, XP M/K, abilities: [id (c/C cd)]`.

Tests: parse each form, malformed rejected.

Commit: `feat(cli): ability command surface + commander status line`

---

## Task 30: Regression gate + spec coverage

- [ ] Run full suite: `uv run pytest -q`
- [ ] Confirm +~50 new tests; all pre-existing 135 still green
- [ ] `uv run ruff check src tests` clean
- [ ] `uv run ruff format --check src tests` clean
- [ ] `uv run mypy --strict src` clean across all source files
- [ ] Walk the spec sections 4.1–4.6, §5 turn flow, §6 ability catalogue — confirm each has a task. No gaps.

If any gap: create a follow-up task, land fix, re-run.

No commit; this is verification.

---

## Merge to main

```bash
git checkout main
git pull
git merge --no-ff feature/sprint5-commander -m "$(cat <<'EOF'
merge: sprint 5 commander system

Adds per-fleet Commander entity with active abilities, passive skills
via PassiveBus, per-ship crew veterancy, command sub-phase at turn
start, auto-assignment in scenarios, battle-end XP + crew tier awards.

All 10 active abilities implemented; torpedo_barrage and augur_probe
resolve as Sprint 6-dependent stubs.  All 15 passives registered.
EOF
)"
git push origin main
```

---

## Self-review — spec coverage checklist

**Spec §4.1 Commander / AbilityState / ActiveBuff** → Task 3.
**Spec §4.2 Fleet extensions** → Task 5.
**Spec §4.3 Ship additions (battles_survived, crew_tier)** → Task 4.
**Spec §4.4 Effect steps** → Tasks 7, 8 (parser), 13–17 (resolvers).
**Spec §4.5 AbilityOrder** → Task 9.
**Spec §4.6 PassiveHook + PassiveBus** → Task 10 (skeleton), 22, 23, 24, 25 (handlers).
**Spec §5 Turn flow — tick clocks** → Task 19.
**Spec §5 COMMAND SUB-PHASE** → Task 19, 20 (interruption), 21 (wire).
**Spec §5 FIRE SUB-PHASE hooks** → Task 22.
**Spec §5 MOVEMENT SUB-PHASE hooks** → Task 12.
**Spec §5 END-OF-TURN hooks** → Task 23.
**Spec §5 GAME-OVER XP + veterancy** → Task 27.
**Spec §5 morale loss path** → Task 11.
**Spec §6 Ability catalogue** → Tasks 13–17, 18 (resolver), 8 (parser), 20 (prep).
**Spec §7 Validation rules** → Task 19.
**Spec §8 Data loading (SkillRegistry)** → Tasks 1, 8.
**Spec §9 Scenario auto-assignment** → Task 26.
**Spec §10 Progression** → Task 2, 27.
**Spec §11 CLI surface** → Task 29.
**Spec §12 Error handling** → Tasks 1 (registry fallback), 19 (ability rejects).
**Spec §13 Testing strategy** → distributed across all task test lists + Task 30 gate.

All spec sections have tasks. No placeholders in the final plan.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-23-sprint5-commander-system.md`.**
