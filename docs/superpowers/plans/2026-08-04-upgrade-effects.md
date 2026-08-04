# Upgrade Effects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 20 catalog upgrades work in battle and at build time — hull stat mods, PassiveBus handlers, direct combat wiring, and slot validation (consuming the deferred Mechanicus `upgrade_slot_bonus`).

**Architecture:** A new `commander/upgrade_effects.py` module that interprets **effect keys** from `UpgradeProfile.effect` dicts (data-driven — new upgrades with existing keys need only yaml). Build-time: `apply_upgrades_to_hull` (mirrors `apply_doctrine_to_hull`) + `build_ship_with_upgrades` + `validate_upgrades`. Runtime: `register_upgrade_handlers` on the PassiveBus (mirrors doctrine handlers) plus direct wiring for AP ammo, lance crits, belt armour, fire suppression, and flagship micro-warp charges.

**Tech Stack:** Python 3.12, uv, pytest, ruff, mypy --strict.

**Spec:** `docs/superpowers/specs/2026-08-04-upgrade-effects-design.md`

## Global Constraints

- Gate before every commit: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q`
- All pre-existing tests stay green. New Ship fields default to no-op.
- Commit messages: human-authored style, no AI attribution, prefix `feat(upgrades):` / `test(upgrades):` / `fix(upgrades):`.
- Upgrades wire into the authoritative net path (`projectile_resolution` + `turn_resolver`) only — the legacy `combat/resolution.py` CLI path is out of scope.

---

## File Structure

- **Modify** `src/spacefleet/data/upgrade_registry.py` — `flagship_only` field + parse.
- **Modify** `src/spacefleet/models/ship.py` — 4 new fields, `from_profile` passthrough, `switch_stance` cooldown reduction.
- **Create** `src/spacefleet/commander/upgrade_effects.py` — all upgrade logic.
- **Modify** `src/spacefleet/commander/passive_skills.py` — one call in `PassiveBus.build`.
- **Modify** `src/spacefleet/combat/damage.py` — `armor_delta` param.
- **Modify** `src/spacefleet/combat/projectile_resolution.py` — AP ammo + lance crit chance.
- **Modify** `src/spacefleet/combat/critical_hits.py` — belt armour gate.
- **Modify** `src/spacefleet/net/turn_resolver.py` — fire suppression + combustion regen bonus.
- **Modify** `src/spacefleet/net/game_state.py` — flagship charge bonus.
- **Create** tests: `tests/test_upgrade_registry_flagship.py`, `tests/test_upgrade_validation.py`, `tests/test_upgrade_effects.py`, `tests/test_upgrade_combat.py`, `tests/test_upgrade_battle.py`.

## Reference: existing APIs (verified 2026-08-04)

- `UpgradeRegistry` (`data/upgrade_registry.py`): class attrs `_upgrades`/`_loaded`; `get`, `get_or_none`, `all`, `reset`. `UpgradeProfile` frozen dataclass: `id, name, category, cost, description, effect: dict[str, Any]`. `_parse(upgrade_id, raw)` builds it; `_coerce_effect_value` turns `"+1"` into `1`. Yaml at `data/upgrades/upgrades.yaml`, key `upgrades:`; `navigators_chamber` has top-level `flagship_only: true` (currently dropped by `_parse`).
- `Ship` dataclass (`models/ship.py`): all fields after `shields_current` have defaults. Doctrine fields sit under `# ── doctrine ──`. `from_profile(ship_id, name, hull, weapons, *, position=None, heading=0.0, speed=0.0, doctrine_id=None, morale_floor=0)`. `switch_stance` currently ends with `self.stance_state.cooldown_remaining = data.switch_cooldown`. `regenerate_combustion(amount: int = 15)`. `battles_survived: int = 0`; `crew_tier` derives from it via `crew_tier_for`.
- `HullProfile` frozen dataclass: `classification: ShipClass`, ints `hull_hits, armor_prow, shields, turrets`, floats `speed, turn_rate, sensor_range`, `base_morale: int = 100`, `assault_actions: int = 0`. Use `dataclasses.replace`.
- `ShipClass` enum: `ESCORT, LIGHT_CRUISER, CRUISER, BATTLECRUISER, BATTLESHIP`.
- `LoadoutError` in `models/loadout.py` (subclass of ValueError).
- Doctrine pattern to mirror (`commander/doctrine_effects.py`): `apply_doctrine_to_hull(hull, doctrine)`, `build_ship_with_doctrine(...)`, `register_doctrine_handlers(bus, state)` iterating `state.ships.values()` with per-ship closures using default-arg binding; `BoardingRepelledByDoctrineEvent(TurnEvent)` dataclass. `DoctrineRegistry.get_or_none(id_or_none)`; `DoctrineDef.upgrade_slot_bonus: int` (deferred consumer = this sub-project); `DoctrineDef.morale_floor: int`.
- `PassiveBus.build(state)` (`commander/passive_skills.py`) ends with local-import call to `register_doctrine_handlers(bus, state)` then `return bus`. Hooks used here: `BATTERY_FIREPOWER_BONUS`, `END_OF_TURN_SHIELD_REGEN`, `TORPEDO_RELOAD_REDUCTION` (all aggregate: handler returns `ctx.value + delta`). `PassiveContext(ship, fleet, state, value, extra)`. Public helpers exist: `battery_firepower_bonus(state, attacker, target, weapon, base=0)`, `end_of_turn_shield_regen(state, ship)`.
- `apply_damage_pipeline(*, target, hits, relative_bearing, damage_per_hit, ignores_armor=False, dice_roller=None)` (`combat/damage.py`): armor branch does `armor = target.armor_for_bearing(relative_bearing)` then per hit `roll >= armor` → penetrate.
- `resolve_projectile_impact(projectile, target, *, dice_roller=None, state=None)` (`combat/projectile_resolution.py`): fetches `attacker = state.ships.get(projectile.attacker_id)`; long-range fp halving uses `projectile.distance_traveled > weapon.weapon.range * 0.5`; calls `apply_damage_pipeline(target=..., hits=..., relative_bearing=incoming_rel, damage_per_hit=..., dice_roller=dr)`.
- `resolve_lance_ray(attacker, weapon, bearing, targets, *, dice_roller=None, state=None)`: after shields, `remaining` penetrating hits deal direct hull damage; **no crit rolls today**. `dr.chance(p)` exists on `DiceRoller`.
- `roll_critical_hit(target, *, lock_on_bonus=False, targeted_subsystem=None, is_temporary=False, dice_roller=None, state=None) -> CriticalResult`; `apply_critical_hit(ship, result) -> None` dispatches on `result.effect` strings: `"shields_collapse", "thrusters_damaged", "weapon_destroyed", "prow_weapons_destroyed", "engine_damaged", "hull_breach", "fire", "bulkhead_collapse", "bridge_destroyed", "magazine_detonation"`. `CriticalResult` is a plain (mutable) dataclass.
- `turn_resolver.resolve_turn` end phase: fire-extinguish leadership check at `if ship.fires > 0: roll = state.dice.d6() ...` emitting `FireExtinguishedEvent`; later `ship.regenerate_combustion(15)`.
- `net/game_state.py`: `_assign_default_commander(state, fleet_id, ship_ids, faction)` picks `flagship`, builds `cmdr = _build_starter_commander(...)`, then constructs `Fleet(...)`. `Commander.ability_state: dict[str, AbilityState]`; `AbilityState(remaining_charges=N)`. `GameState()` no-arg works; `state.add_ship(ship)` exists; `state.dice` is a `DiceRoller` (injectable seed).
- `SkillRegistry.get_crew_tier(tier) -> CrewTierDef | None` with `.battles_required` (tier 2 fallback = 5).
- Test helpers: `from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons, SALVAGE_GUN, LANCE_2`; `WeaponMount(slot_id=..., slot_name=..., arc=..., weapon=...)`; pattern in `tests/test_doctrine_battle.py` (`GameState()` + `add_ship` + `resolve_turn(state, {sid: Command(...)})`).
- `TurnEvent` base: `from spacefleet.core.events import TurnEvent`.
- Registries cache module-level — call `.reset()` in tests that depend on yaml-loaded content.

---

## Task 1: `UpgradeProfile.flagship_only`

**Files:**
- Modify: `src/spacefleet/data/upgrade_registry.py`
- Test: `tests/test_upgrade_registry_flagship.py`

**Interfaces:**
- Produces: `UpgradeProfile.flagship_only: bool` (default `False`), parsed from the yaml top-level `flagship_only` key.

- [ ] **Step 1: Write the failing test**

```python
"""UpgradeRegistry — flagship_only flag parsing."""

from __future__ import annotations

from spacefleet.data.upgrade_registry import UpgradeRegistry


def test_navigators_chamber_is_flagship_only() -> None:
    UpgradeRegistry.reset()
    nav = UpgradeRegistry.get("navigators_chamber")
    assert nav.flagship_only is True


def test_other_upgrades_default_not_flagship_only() -> None:
    UpgradeRegistry.reset()
    assert UpgradeRegistry.get("turbo_weaponry").flagship_only is False
    assert UpgradeRegistry.get("additional_void_shield").flagship_only is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_registry_flagship.py -v`
Expected: FAIL — `AttributeError: 'UpgradeProfile' object has no attribute 'flagship_only'`

- [ ] **Step 3: Implement**

In `UpgradeProfile`, after `description: str = ""` add:

```python
    flagship_only: bool = False
```

In `_parse`, extend the `UpgradeProfile(...)` construction:

```python
            flagship_only=bool(raw.get("flagship_only", False)),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_registry_flagship.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/data/upgrade_registry.py tests/test_upgrade_registry_flagship.py
git commit -m "feat(upgrades): flagship_only flag on UpgradeProfile"
```

---

## Task 2: Ship upgrade fields + stance cooldown reduction

**Files:**
- Modify: `src/spacefleet/models/ship.py`
- Test: `tests/test_upgrade_effects.py` (new file, first tests)

**Interfaces:**
- Produces: `Ship.upgrade_ids: list[str]`, `Ship.stance_cooldown_reduction: int`, `Ship.combustion_regen_bonus: int`, `Ship.belt_armour_spent: bool`; `Ship.from_profile(..., upgrade_ids: list[str] | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
"""Upgrade effects — Ship fields, hull mods, ship builder."""

from __future__ import annotations

from spacefleet.core.types import Stance
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.ship import Ship


def _ship(**kwargs: object) -> Ship:
    return Ship.from_profile("s1", "Test Ship", HULK_HULL, make_hulk_weapons(), **kwargs)  # type: ignore[arg-type]


def test_ship_upgrade_fields_default_noop() -> None:
    ship = _ship()
    assert ship.upgrade_ids == []
    assert ship.stance_cooldown_reduction == 0
    assert ship.combustion_regen_bonus == 0
    assert ship.belt_armour_spent is False


def test_from_profile_upgrade_ids_passthrough() -> None:
    ship = _ship(upgrade_ids=["turbo_weaponry"])
    assert ship.upgrade_ids == ["turbo_weaponry"]


def test_stance_cooldown_reduction_applies_on_switch() -> None:
    plain = _ship()
    reduced = _ship()
    reduced.stance_cooldown_reduction = 1
    assert plain.switch_stance(Stance.LOCK_ON) is True
    assert reduced.switch_stance(Stance.LOCK_ON) is True
    assert reduced.stance_cooldown_remaining == max(0, plain.stance_cooldown_remaining - 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_effects.py -v`
Expected: FAIL — `TypeError: Ship.from_profile() got an unexpected keyword argument 'upgrade_ids'` (first failure)

- [ ] **Step 3: Implement**

In `Ship`, after the `# ── doctrine ──` block add:

```python
    # ── upgrades ──
    upgrade_ids: list[str] = field(default_factory=list)
    stance_cooldown_reduction: int = 0
    combustion_regen_bonus: int = 0
    belt_armour_spent: bool = False
```

In `switch_stance`, replace the final assignment:

```python
        self.stance_state.cooldown_remaining = max(
            0, data.switch_cooldown - self.stance_cooldown_reduction
        )
```

In `from_profile`, add keyword param `upgrade_ids: list[str] | None = None` (after `morale_floor: int = 0`) and pass `upgrade_ids=list(upgrade_ids or [])` in the `cls(...)` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_effects.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/models/ship.py tests/test_upgrade_effects.py
git commit -m "feat(ship): upgrade fields with stance-cooldown reduction"
```

---

## Task 3: Effect-key helpers + slot caps + `validate_upgrades`

**Files:**
- Create: `src/spacefleet/commander/upgrade_effects.py`
- Test: `tests/test_upgrade_validation.py`

**Interfaces:**
- Produces (all in `spacefleet.commander.upgrade_effects`):
  - `upgrade_effect_total(upgrade_ids: list[str], key: str) -> float`
  - `upgrade_has_effect(upgrade_ids: list[str], key: str) -> bool`
  - `UPGRADE_SLOT_CAPS: dict[ShipClass, int]` = `{ESCORT: 1, LIGHT_CRUISER: 2, CRUISER: 3, BATTLECRUISER: 3, BATTLESHIP: 4}`
  - `upgrade_slots_for(hull: HullProfile, doctrine_id: str | None = None) -> int`
  - `validate_upgrades(hull: HullProfile, upgrade_ids: list[str], *, doctrine_id: str | None = None, is_flagship: bool = False) -> None` — raises `LoadoutError`

- [ ] **Step 1: Write the failing test**

```python
"""Upgrade build-time validation — slot caps, ids, flagship-only."""

from __future__ import annotations

import dataclasses

import pytest

from spacefleet.commander.upgrade_effects import (
    upgrade_effect_total,
    upgrade_has_effect,
    upgrade_slots_for,
    validate_upgrades,
)
from spacefleet.core.types import ShipClass
from spacefleet.data.demo_data import HULK_HULL
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.models.loadout import LoadoutError

_ESCORT_HULL = dataclasses.replace(HULK_HULL, classification=ShipClass.ESCORT)
_BATTLESHIP_HULL = dataclasses.replace(HULK_HULL, classification=ShipClass.BATTLESHIP)


def setup_function() -> None:
    UpgradeRegistry.reset()


def test_effect_total_sums_across_upgrades() -> None:
    total = upgrade_effect_total(["additional_void_shield", "turbo_weaponry"], "shields")
    assert total == 1
    assert upgrade_effect_total([], "shields") == 0
    assert upgrade_effect_total(["nonexistent"], "shields") == 0  # unknown ids skipped


def test_has_effect() -> None:
    assert upgrade_has_effect(["belt_armour"], "first_crit_ignored") is True
    assert upgrade_has_effect(["turbo_weaponry"], "first_crit_ignored") is False


def test_slots_by_class() -> None:
    assert upgrade_slots_for(_ESCORT_HULL) == 1
    assert upgrade_slots_for(_BATTLESHIP_HULL) == 4


def test_mechanicus_rites_grants_extra_slot() -> None:
    assert upgrade_slots_for(_ESCORT_HULL, doctrine_id="mechanicus_rites") == 2


def test_validate_rejects_unknown_id() -> None:
    with pytest.raises(LoadoutError, match="unknown upgrade"):
        validate_upgrades(_BATTLESHIP_HULL, ["warp_cannon_xxl"])


def test_validate_rejects_duplicates() -> None:
    with pytest.raises(LoadoutError, match="duplicate"):
        validate_upgrades(_BATTLESHIP_HULL, ["turbo_weaponry", "turbo_weaponry"])


def test_validate_rejects_over_slot_cap() -> None:
    with pytest.raises(LoadoutError, match="slots"):
        validate_upgrades(_ESCORT_HULL, ["turbo_weaponry", "reinforced_prow"])


def test_validate_rejects_flagship_only_on_escort() -> None:
    with pytest.raises(LoadoutError, match="flagship"):
        validate_upgrades(_ESCORT_HULL, ["navigators_chamber"], is_flagship=False)
    validate_upgrades(_ESCORT_HULL, ["navigators_chamber"], is_flagship=True)  # ok


def test_validate_accepts_valid_loadout() -> None:
    validate_upgrades(_BATTLESHIP_HULL, ["turbo_weaponry", "belt_armour", "crew_quarters"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spacefleet.commander.upgrade_effects'`

- [ ] **Step 3: Implement**

Create `src/spacefleet/commander/upgrade_effects.py`:

```python
"""Upgrade effects — build-time stat mods, runtime PassiveBus handlers,
and build-time validation. Interprets *effect keys* from the upgrade
catalog (data-driven): new upgrades reusing existing keys need only yaml."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.core.types import ShipClass
from spacefleet.data.upgrade_registry import UpgradeProfile, UpgradeRegistry
from spacefleet.models.loadout import LoadoutError

if TYPE_CHECKING:
    from spacefleet.models.ship_profile import HullProfile


UPGRADE_SLOT_CAPS: dict[ShipClass, int] = {
    ShipClass.ESCORT: 1,
    ShipClass.LIGHT_CRUISER: 2,
    ShipClass.CRUISER: 3,
    ShipClass.BATTLECRUISER: 3,
    ShipClass.BATTLESHIP: 4,
}


def _profiles(upgrade_ids: list[str]) -> list[UpgradeProfile]:
    """Resolve ids to profiles, silently skipping unknown ids
    (validation reports them; runtime helpers stay total)."""
    found = (UpgradeRegistry.get_or_none(uid) for uid in upgrade_ids)
    return [p for p in found if p is not None]


def upgrade_effect_total(upgrade_ids: list[str], key: str) -> float:
    """Sum of a numeric effect *key* across the ship's upgrades."""
    total = 0.0
    for prof in _profiles(upgrade_ids):
        value = prof.effect.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += value
    return total


def upgrade_has_effect(upgrade_ids: list[str], key: str) -> bool:
    """True if any of the ship's upgrades declares a truthy *key*."""
    return any(prof.effect.get(key) for prof in _profiles(upgrade_ids))


def upgrade_slots_for(hull: HullProfile, doctrine_id: str | None = None) -> int:
    """Upgrade slot cap for *hull*, plus any doctrine bonus (Mechanicus Rites)."""
    from spacefleet.data.doctrine_registry import DoctrineRegistry

    slots = UPGRADE_SLOT_CAPS.get(hull.classification, 1)
    doctrine = DoctrineRegistry.get_or_none(doctrine_id)
    if doctrine is not None:
        slots += doctrine.upgrade_slot_bonus
    return slots


def validate_upgrades(
    hull: HullProfile,
    upgrade_ids: list[str],
    *,
    doctrine_id: str | None = None,
    is_flagship: bool = False,
) -> None:
    """Raise :class:`LoadoutError` if *upgrade_ids* are illegal for *hull*."""
    for uid in upgrade_ids:
        if UpgradeRegistry.get_or_none(uid) is None:
            raise LoadoutError(f"unknown upgrade id {uid!r}")
    if len(set(upgrade_ids)) != len(upgrade_ids):
        raise LoadoutError(f"duplicate upgrade ids in {upgrade_ids}")
    slots = upgrade_slots_for(hull, doctrine_id)
    if len(upgrade_ids) > slots:
        raise LoadoutError(
            f"{len(upgrade_ids)} upgrades exceed {slots} slots"
            f" for {hull.classification.value}"
        )
    if not is_flagship:
        for prof in _profiles(upgrade_ids):
            if prof.flagship_only:
                raise LoadoutError(f"upgrade {prof.id!r} is flagship-only")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_validation.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/commander/upgrade_effects.py tests/test_upgrade_validation.py
git commit -m "feat(upgrades): effect-key helpers, slot caps, build validation"
```

---

## Task 4: Hull stat mods + `build_ship_with_upgrades`

**Files:**
- Modify: `src/spacefleet/commander/upgrade_effects.py`
- Test: `tests/test_upgrade_effects.py` (append)

**Interfaces:**
- Consumes: Task 2 Ship fields; Task 3 helpers; `apply_doctrine_to_hull` + `DoctrineRegistry` from the doctrine sub-project; `SkillRegistry.get_crew_tier`.
- Produces:
  - `apply_upgrades_to_hull(hull: HullProfile, upgrade_ids: list[str]) -> HullProfile`
  - `build_ship_with_upgrades(ship_id, name, hull, weapons, *, upgrade_ids, doctrine_id=None, position=None, heading=0.0) -> Ship`

- [ ] **Step 1: Write the failing test** (append to `tests/test_upgrade_effects.py`)

```python
from spacefleet.commander.upgrade_effects import (
    apply_upgrades_to_hull,
    build_ship_with_upgrades,
)
from spacefleet.data.upgrade_registry import UpgradeRegistry


def test_apply_upgrades_to_hull_stats() -> None:
    UpgradeRegistry.reset()
    modded = apply_upgrades_to_hull(
        HULK_HULL,
        [
            "additional_void_shield",
            "reinforced_prow",
            "extra_turrets",
            "efficient_plasma_thrusters",
            "enhanced_maneuvers",
            "improved_augur_array",
            "crew_quarters",
        ],
    )
    assert modded.shields == HULK_HULL.shields + 1
    assert modded.armor_prow == HULK_HULL.armor_prow + 1
    assert modded.turrets == HULK_HULL.turrets + 2
    assert modded.speed == HULK_HULL.speed + 5
    assert modded.turn_rate == HULK_HULL.turn_rate + 15
    assert modded.sensor_range == HULK_HULL.sensor_range + 20
    assert modded.base_morale == HULK_HULL.base_morale + 15


def test_build_ship_with_upgrades_state_fields() -> None:
    UpgradeRegistry.reset()
    ship = build_ship_with_upgrades(
        "up1",
        "Upgraded",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=[
            "extended_combustion_tanks",
            "veteran_crew",
            "master_of_signals",
        ],
    )
    assert ship.combustion_max == 125
    assert ship.combustion == 125  # starts full
    assert ship.combustion_regen_bonus == 5
    assert ship.stance_cooldown_reduction == 1
    assert ship.crew_tier == 2  # veteran_crew → Experienced
    assert ship.upgrade_ids == [
        "extended_combustion_tanks",
        "veteran_crew",
        "master_of_signals",
    ]


def test_build_ship_with_upgrades_composes_with_doctrine() -> None:
    UpgradeRegistry.reset()
    ship = build_ship_with_upgrades(
        "up2",
        "Upgraded Nurgle",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["additional_void_shield"],
        doctrine_id="mark_of_nurgle",
    )
    # Nurgle: +2 hull, -5 speed; upgrade: +1 shields
    assert ship.hull_max == HULK_HULL.hull_hits + 2
    assert ship.shields_max == HULK_HULL.shields + 1
    assert ship.doctrine_id == "mark_of_nurgle"


def test_build_ship_without_upgrades_is_plain() -> None:
    ship = build_ship_with_upgrades(
        "up3", "Plain", HULK_HULL, make_hulk_weapons(), upgrade_ids=[]
    )
    assert ship.hull_max == HULK_HULL.hull_hits
    assert ship.combustion_max == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_effects.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_upgrades_to_hull'`

- [ ] **Step 3: Implement** (append to `upgrade_effects.py`)

```python
import dataclasses

from spacefleet.models.ship import Ship

# (move these imports to the top of the file, merged with existing ones;
#  TYPE_CHECKING gains: from spacefleet.core.types import Vector2D
#  and: from spacefleet.models.weapon import WeaponMount)


def apply_upgrades_to_hull(hull: HullProfile, upgrade_ids: list[str]) -> HullProfile:
    """Hull copy with all upgrade stat deltas applied (clamped sane)."""
    if not upgrade_ids:
        return hull
    return dataclasses.replace(
        hull,
        shields=max(0, hull.shields + int(upgrade_effect_total(upgrade_ids, "shields"))),
        armor_prow=max(0, hull.armor_prow + int(upgrade_effect_total(upgrade_ids, "armor_prow"))),
        turrets=max(0, hull.turrets + int(upgrade_effect_total(upgrade_ids, "turrets"))),
        speed=max(0.0, hull.speed + upgrade_effect_total(upgrade_ids, "speed")),
        turn_rate=max(0.0, hull.turn_rate + upgrade_effect_total(upgrade_ids, "turn_rate")),
        sensor_range=max(
            0.0, hull.sensor_range + upgrade_effect_total(upgrade_ids, "sensor_range")
        ),
        base_morale=max(1, hull.base_morale + int(upgrade_effect_total(upgrade_ids, "morale_max"))),
    )


def build_ship_with_upgrades(
    ship_id: str,
    name: str,
    hull: HullProfile,
    weapons: list[WeaponMount],
    *,
    upgrade_ids: list[str],
    doctrine_id: str | None = None,
    position: Vector2D | None = None,
    heading: float = 0.0,
) -> Ship:
    """Construct a Ship applying doctrine then upgrade effects.

    Doctrine hull mods apply first (same order the fleet builder will use),
    then upgrade hull mods, then upgrade-derived mutable state.
    """
    from spacefleet.commander.doctrine_effects import apply_doctrine_to_hull
    from spacefleet.data.doctrine_registry import DoctrineRegistry
    from spacefleet.data.skill_registry import SkillRegistry

    doctrine = DoctrineRegistry.get_or_none(doctrine_id)
    final_hull = apply_doctrine_to_hull(hull, doctrine) if doctrine is not None else hull
    final_hull = apply_upgrades_to_hull(final_hull, upgrade_ids)
    ship = Ship.from_profile(
        ship_id,
        name,
        final_hull,
        weapons,
        position=position,
        heading=heading,
        doctrine_id=doctrine_id,
        morale_floor=doctrine.morale_floor if doctrine is not None else 0,
        upgrade_ids=upgrade_ids,
    )

    combustion_bonus = int(upgrade_effect_total(upgrade_ids, "combustion_max"))
    ship.combustion_max += combustion_bonus
    ship.combustion += combustion_bonus
    ship.combustion_regen_bonus = int(upgrade_effect_total(upgrade_ids, "combustion_regen"))
    ship.stance_cooldown_reduction = int(
        upgrade_effect_total(upgrade_ids, "stance_cooldown_reduction")
    )

    tiers = [
        int(p.effect["starting_crew_tier"])
        for p in _profiles(upgrade_ids)
        if "starting_crew_tier" in p.effect
    ]
    if tiers:
        tier_def = SkillRegistry.get_crew_tier(max(tiers))
        if tier_def is not None:
            ship.battles_survived = max(ship.battles_survived, tier_def.battles_required)

    return ship
```

Note for the implementer: keep all imports at the top of the file (module-level `dataclasses`, `Ship`; `TYPE_CHECKING` for `Vector2D`, `WeaponMount`, `HullProfile`). Local imports inside functions only where the doctrine module does the same (registry/doctrine/skill lookups) to avoid import cycles.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_effects.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/commander/upgrade_effects.py tests/test_upgrade_effects.py
git commit -m "feat(upgrades): hull stat mods + upgrade-aware ship builder"
```

---

## Task 5: PassiveBus handlers (turbo weaponry, shield capacitor, automated reload)

**Files:**
- Modify: `src/spacefleet/commander/upgrade_effects.py`
- Modify: `src/spacefleet/commander/passive_skills.py`
- Test: `tests/test_upgrade_effects.py` (append)

**Interfaces:**
- Consumes: `PassiveBus`, `PassiveContext`, `PassiveHook` from `passive_skills`; `battery_firepower_bonus` / `end_of_turn_shield_regen` public helpers.
- Produces: `register_upgrade_handlers(bus: PassiveBus, state: CoreGameState) -> None`, called from `PassiveBus.build`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_upgrade_effects.py`)

```python
from spacefleet.commander.passive_skills import (
    PassiveBus,
    battery_firepower_bonus,
    end_of_turn_shield_regen,
)
from spacefleet.core.types import Vector2D
from spacefleet.net.game_state import GameState


def test_turbo_weaponry_and_capacitor_register_per_ship() -> None:
    UpgradeRegistry.reset()
    state = GameState()
    upgraded = build_ship_with_upgrades(
        "u1",
        "Upgraded",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["turbo_weaponry", "auxiliary_shield_capacitor"],
        position=Vector2D(0, 0),
    )
    plain = Ship.from_profile("p1", "Plain", HULK_HULL, make_hulk_weapons())
    state.add_ship(upgraded)
    state.add_ship(plain)
    state.passives = PassiveBus.build(state)

    weapon = upgraded.weapons[0]
    assert battery_firepower_bonus(state, upgraded, plain, weapon) == 1
    assert battery_firepower_bonus(state, plain, upgraded, weapon) == 0  # isolation
    assert end_of_turn_shield_regen(state, upgraded) == 1
    assert end_of_turn_shield_regen(state, plain) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_effects.py::test_turbo_weaponry_and_capacitor_register_per_ship -v`
Expected: FAIL — bonuses come back 0 (no handlers registered)

- [ ] **Step 3: Implement**

Append to `upgrade_effects.py` (add `PassiveContext`, `PassiveHook` to the module-level imports from `spacefleet.commander.passive_skills`; `TYPE_CHECKING` gains `PassiveBus` and `CoreGameState` — exactly like `doctrine_effects.py` does):

```python
def register_upgrade_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Per-ship PassiveBus handlers keyed on ``ship.upgrade_ids``."""
    from typing import Any

    for ship in state.ships.values():
        if not ship.upgrade_ids:
            continue
        sid = ship.id

        battery = int(upgrade_effect_total(ship.upgrade_ids, "battery_strength"))
        if battery:

            def _battery(ctx: PassiveContext, s: str = sid, v: int = battery) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:upgrade_battery",
                hook=PassiveHook.BATTERY_FIREPOWER_BONUS,
                handler=_battery,
            )

        regen = int(upgrade_effect_total(ship.upgrade_ids, "shield_regen"))
        if regen:

            def _regen(ctx: PassiveContext, s: str = sid, v: int = regen) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:upgrade_shield_regen",
                hook=PassiveHook.END_OF_TURN_SHIELD_REGEN,
                handler=_regen,
            )

        reload = int(upgrade_effect_total(ship.upgrade_ids, "torpedo_reload_reduction"))
        if reload:

            def _reload(ctx: PassiveContext, s: str = sid, v: int = reload) -> Any:
                return ctx.value - v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            # Inert until Sprint-6 torpedoes exist — registration proves loadability.
            bus.register(
                source=f"{sid}:upgrade_reload",
                hook=PassiveHook.TORPEDO_RELOAD_REDUCTION,
                handler=_reload,
            )
```

(Implementer note: `from typing import Any` belongs at module top, not inside the function.)

In `passive_skills.py`, `PassiveBus.build`, after the `register_doctrine_handlers(bus, state)` call add:

```python
        from spacefleet.commander.upgrade_effects import register_upgrade_handlers

        register_upgrade_handlers(bus, state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_effects.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/commander/upgrade_effects.py src/spacefleet/commander/passive_skills.py tests/test_upgrade_effects.py
git commit -m "feat(upgrades): per-ship passive handlers on the bus"
```

---

## Task 6: Armour-piercing ammo (close-range armor delta)

**Files:**
- Modify: `src/spacefleet/combat/damage.py`
- Modify: `src/spacefleet/combat/projectile_resolution.py`
- Modify: `src/spacefleet/commander/upgrade_effects.py` (accessor)
- Test: `tests/test_upgrade_combat.py` (new)

**Interfaces:**
- Produces: `apply_damage_pipeline(..., armor_delta: int = 0)`; `ap_armor_delta(ship: Ship) -> int` in `upgrade_effects` (returns `-int(total("ap_close_range"))`, i.e. `-1` with the upgrade, `0` without).

- [ ] **Step 1: Write the failing test**

```python
"""Upgrade combat wiring — AP ammo, lance crits, belt armour."""

from __future__ import annotations

import dataclasses

from spacefleet.combat.damage import apply_damage_pipeline
from spacefleet.combat.projectile_resolution import resolve_projectile_impact
from spacefleet.commander.upgrade_effects import build_ship_with_upgrades
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, SALVAGE_GUN, make_hulk_weapons
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.dice import DiceRoller
from spacefleet.models.projectile import Projectile
from spacefleet.models.ship import Ship
from spacefleet.net.game_state import GameState


class _FixedDice(DiceRoller):
    """d6 always returns *value*; chance() always True."""

    def __init__(self, value: int) -> None:
        super().__init__(seed=1)
        self._value = value

    def d6(self) -> int:
        return self._value

    def chance(self, probability: float) -> bool:
        return probability > 0


def test_armor_delta_lowers_effective_armor() -> None:
    armor5_hull = dataclasses.replace(
        HULK_HULL, armor_prow=5, armor_port=5, armor_starboard=5, armor_stern=5, shields=0
    )
    target = Ship.from_profile("t", "Target", armor5_hull, make_hulk_weapons())
    # Roll of 4 vs armor 5: saved without delta...
    report = apply_damage_pipeline(
        target=target,
        hits=1,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=_FixedDice(4),
    )
    assert report.penetrating == 0
    # ...but penetrates with armor_delta=-1 (AP ammo at close range).
    report = apply_damage_pipeline(
        target=target,
        hits=1,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=_FixedDice(4),
        armor_delta=-1,
    )
    assert report.penetrating == 1


def _projectile_from(attacker: Ship, distance_traveled: float) -> Projectile:
    proj = Projectile(
        id="pr1",
        position=Vector2D(0, 0),
        bearing=0.0,
        speed=SALVAGE_GUN.speed,
        weapon_mount=attacker.weapons[0],
        attacker_id=attacker.id,
        attacker_name=attacker.name,
        attacker_faction=attacker.faction,
        origin=Vector2D(0, 0),
        max_range=SALVAGE_GUN.range,
    )
    proj.distance_traveled = distance_traveled
    return proj


def test_ap_ammo_applies_only_at_close_range() -> None:
    UpgradeRegistry.reset()
    armor5_hull = dataclasses.replace(
        HULK_HULL, armor_prow=5, armor_port=5, armor_starboard=5, armor_stern=5, shields=0
    )
    state = GameState()
    attacker = build_ship_with_upgrades(
        "ap", "AP Ship", HULK_HULL, make_hulk_weapons(), upgrade_ids=["armour_piercing_ammo"]
    )
    target = Ship.from_profile("t2", "Target", armor5_hull, make_hulk_weapons())
    state.add_ship(attacker)
    state.add_ship(target)

    close = resolve_projectile_impact(
        _projectile_from(attacker, SALVAGE_GUN.range * 0.25),
        target,
        dice_roller=_FixedDice(4),
        state=state,
    )
    assert close.penetrating_hits > 0  # armor 5 → 4 with AP; roll 4 penetrates

    target.hull_current = target.hull_max  # reset
    far = resolve_projectile_impact(
        _projectile_from(attacker, SALVAGE_GUN.range * 0.9),
        target,
        dice_roller=_FixedDice(4),
        state=state,
    )
    assert far.penetrating_hits == 0  # no AP at long range; roll 4 vs armor 5 saved
```

Note: if `Projectile` computes `distance_traveled` as a property from `origin`/`position` instead of a settable attribute, set `proj.position` so that the traveled distance matches instead of assigning directly — check `models/projectile.py` before writing.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_combat.py -v`
Expected: FAIL — `TypeError: apply_damage_pipeline() got an unexpected keyword argument 'armor_delta'`

- [ ] **Step 3: Implement**

`damage.py` — add param `armor_delta: int = 0` to `apply_damage_pipeline` (document: "negative lowers the target's effective armor — armour-piercing ammunition") and change the armor line:

```python
    armor = max(1, target.armor_for_bearing(relative_bearing) + armor_delta)
```

`upgrade_effects.py` — add:

```python
def ap_armor_delta(ship: Ship) -> int:
    """Armor delta from armour-piercing ammunition (negative or 0)."""
    return -int(upgrade_effect_total(ship.upgrade_ids, "ap_close_range"))
```

`projectile_resolution.py`, in `resolve_projectile_impact`, before the pipeline call:

```python
    armor_delta = 0
    if attacker is not None and projectile.distance_traveled <= weapon.weapon.range * 0.5:
        from spacefleet.commander.upgrade_effects import ap_armor_delta

        armor_delta = ap_armor_delta(attacker)
```

and pass `armor_delta=armor_delta` to `apply_damage_pipeline`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_combat.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/combat/damage.py src/spacefleet/combat/projectile_resolution.py src/spacefleet/commander/upgrade_effects.py tests/test_upgrade_combat.py
git commit -m "feat(upgrades): armour-piercing ammo lowers armor at close range"
```

---

## Task 7: Disruption overcharge (lance crit chance)

**Files:**
- Modify: `src/spacefleet/combat/projectile_resolution.py`
- Modify: `src/spacefleet/commander/upgrade_effects.py` (accessor)
- Test: `tests/test_upgrade_combat.py` (append)

**Interfaces:**
- Produces: `lance_crit_chance(ship: Ship) -> float` (0.25 with the upgrade, 0.0 without); `resolve_lance_ray` rolls a critical per penetrating hit with that probability.

- [ ] **Step 1: Write the failing test** (append)

```python
from spacefleet.data.demo_data import LANCE_2
from spacefleet.models.weapon import WeaponMount
from spacefleet.core.types import Arc


def _lance_mount() -> WeaponMount:
    return WeaponMount(slot_id=1, slot_name="Lance", arc=Arc.PROW, weapon=LANCE_2)


def test_disruption_overcharge_triggers_lance_crits() -> None:
    UpgradeRegistry.reset()
    from spacefleet.combat.projectile_resolution import resolve_lance_ray
    from spacefleet.core.types import Faction

    state = GameState()
    attacker = build_ship_with_upgrades(
        "lc",
        "Lancer",
        HULK_HULL,
        [_lance_mount()],
        upgrade_ids=["disruption_overcharge"],
        position=Vector2D(0, 0),
    )
    target = Ship.from_profile(
        "lt", "Lance Target", HULK_HULL, make_hulk_weapons(), position=Vector2D(0, 10)
    )
    target.faction = Faction.CHAOS_FLEET
    target.shields_current = 0
    state.add_ship(attacker)
    state.add_ship(target)

    dice = _FixedDice(6)  # every lance die hits; chance() always True
    result = resolve_lance_ray(
        attacker, attacker.weapons[0], 0.0, [target], dice_roller=dice, state=state
    )
    assert result is not None
    assert result.penetrating_hits > 0
    assert len(result.critical_hits) == result.penetrating_hits


def test_no_lance_crits_without_upgrade() -> None:
    from spacefleet.combat.projectile_resolution import resolve_lance_ray
    from spacefleet.core.types import Faction

    state = GameState()
    attacker = Ship.from_profile(
        "lc2", "Plain Lancer", HULK_HULL, [_lance_mount()], position=Vector2D(0, 0)
    )
    target = Ship.from_profile(
        "lt2", "Lance Target", HULK_HULL, make_hulk_weapons(), position=Vector2D(0, 10)
    )
    target.faction = Faction.CHAOS_FLEET
    target.shields_current = 0
    state.add_ship(attacker)
    state.add_ship(target)

    result = resolve_lance_ray(
        attacker, attacker.weapons[0], 0.0, [target], dice_roller=_FixedDice(6), state=state
    )
    assert result is not None
    assert result.critical_hits == []
```

Caveat for `_FixedDice(6)`: `roll_2d6` inside `roll_critical_hit` will return 12 (Magazine Detonation, D6 extra damage = 6). `HULK_HULL` has 8+ hull? If the target dies to crit damage the assertion `len(critical_hits) == penetrating_hits` may fail because the loop breaks on destruction. Guard by giving the target a fat hull: `dataclasses.replace(HULK_HULL, hull_hits=99)` — adjust the test accordingly (use that hull for `lt`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_combat.py -v`
Expected: FAIL — `result.critical_hits == []` in the upgraded case

- [ ] **Step 3: Implement**

`upgrade_effects.py`:

```python
def lance_crit_chance(ship: Ship) -> float:
    """Probability a penetrating lance hit triggers a critical (disruption overcharge)."""
    return float(upgrade_effect_total(ship.upgrade_ids, "lance_critical_bonus"))
```

`projectile_resolution.py`, in `resolve_lance_ray`, after the hull-damage application (after the `if result.hull_damage_dealt > 0:` block, before the summary):

```python
    # Disruption overcharge — chance of a critical per penetrating hit.
    if result.penetrating_hits > 0 and best_target.alive:
        from spacefleet.commander.upgrade_effects import lance_crit_chance

        crit_p = lance_crit_chance(attacker)
        if crit_p > 0:
            from spacefleet.combat.critical_hits import apply_critical_hit, roll_critical_hit

            for _ in range(result.penetrating_hits):
                if not best_target.alive:
                    break
                if not dr.chance(crit_p):
                    continue
                crit = roll_critical_hit(best_target, dice_roller=dr, state=state)
                apply_critical_hit(best_target, crit)
                result.critical_hits.append(crit)
                if not best_target.alive:
                    result.target_destroyed = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_combat.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/combat/projectile_resolution.py src/spacefleet/commander/upgrade_effects.py tests/test_upgrade_combat.py
git commit -m "feat(upgrades): disruption overcharge grants lance crit chance"
```

---

## Task 8: Belt armour (first subsystem crit ignored)

**Files:**
- Modify: `src/spacefleet/combat/critical_hits.py`
- Test: `tests/test_upgrade_combat.py` (append)

**Interfaces:**
- Consumes: `Ship.belt_armour_spent` (Task 2), `upgrade_has_effect` (Task 3).
- Produces: `CriticalResult.ignored_by_belt_armour: bool = False`; `apply_critical_hit` skips the first subsystem-affecting crit on a belt-armour ship.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_belt_armour_ignores_first_subsystem_crit_only() -> None:
    UpgradeRegistry.reset()
    from spacefleet.combat.critical_hits import CriticalResult, apply_critical_hit

    ship = build_ship_with_upgrades(
        "ba", "Armoured", HULK_HULL, make_hulk_weapons(), upgrade_ids=["belt_armour"]
    )

    first = CriticalResult(roll=3, name="Thrusters Damaged", effect="thrusters_damaged")
    apply_critical_hit(ship, first)
    assert first.ignored_by_belt_armour is True
    assert ship.crit_thrusters_damaged is False  # ignored
    assert ship.belt_armour_spent is True

    second = CriticalResult(roll=3, name="Thrusters Damaged", effect="thrusters_damaged")
    apply_critical_hit(ship, second)
    assert second.ignored_by_belt_armour is False
    assert ship.crit_thrusters_damaged is True  # belt spent, crit lands


def test_belt_armour_does_not_block_structural_crits() -> None:
    UpgradeRegistry.reset()
    from spacefleet.combat.critical_hits import CriticalResult, apply_critical_hit

    ship = build_ship_with_upgrades(
        "ba2", "Armoured", HULK_HULL, make_hulk_weapons(), upgrade_ids=["belt_armour"]
    )
    hull_before = ship.hull_current
    breach = CriticalResult(roll=7, name="Hull Breach", effect="hull_breach", extra_damage=1)
    apply_critical_hit(ship, breach)
    assert breach.ignored_by_belt_armour is False
    assert ship.hull_current < hull_before  # structural damage applied
    assert ship.belt_armour_spent is False  # belt untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_combat.py -v`
Expected: FAIL — `TypeError: CriticalResult.__init__() got an unexpected keyword argument 'ignored_by_belt_armour'` or the thrusters assertion

- [ ] **Step 3: Implement**

`critical_hits.py` — add to `CriticalResult` (end of fields):

```python
    ignored_by_belt_armour: bool = False
```

Add module constant near the crit table:

```python
# Subsystem-affecting crit effects — the ones Belt Armour can absorb.
# Structural crits (hull_breach, fire, bulkhead_collapse, magazine_detonation)
# are not blocked.
_SUBSYSTEM_CRIT_EFFECTS = frozenset(
    {
        "shields_collapse",
        "thrusters_damaged",
        "weapon_destroyed",
        "prow_weapons_destroyed",
        "engine_damaged",
        "bridge_destroyed",
    }
)
```

At the top of `apply_critical_hit`, before the effect dispatch:

```python
    if (
        result.effect in _SUBSYSTEM_CRIT_EFFECTS
        and not ship.belt_armour_spent
        and ship.upgrade_ids
    ):
        from spacefleet.commander.upgrade_effects import upgrade_has_effect

        if upgrade_has_effect(ship.upgrade_ids, "first_crit_ignored"):
            ship.belt_armour_spent = True
            result.ignored_by_belt_armour = True
            return
```

(Local import keeps `combat` free of a hard dependency on `commander` — same pattern the module already uses elsewhere.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_combat.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/combat/critical_hits.py tests/test_upgrade_combat.py
git commit -m "feat(upgrades): belt armour absorbs first subsystem critical"
```

---

## Task 9: Fire suppression + combustion regen bonus (end phase)

**Files:**
- Modify: `src/spacefleet/net/turn_resolver.py`
- Modify: `src/spacefleet/commander/upgrade_effects.py` (event + accessor)
- Test: `tests/test_upgrade_battle.py` (new)

**Interfaces:**
- Produces: `FireSuppressedByUpgradeEvent(TurnEvent)` dataclass with `ship_id: str`, `fires_remaining: int` in `upgrade_effects`; `fire_extinguish_chance(ship: Ship) -> float`; end phase rolls it before the leadership check; combustion regen becomes `15 + ship.combustion_regen_bonus`.

- [ ] **Step 1: Write the failing test**

```python
"""Upgrade effects exercised through resolve_turn."""

from __future__ import annotations

from spacefleet.commander.upgrade_effects import (
    FireSuppressedByUpgradeEvent,
    build_ship_with_upgrades,
)
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import resolve_turn


class _AlwaysChanceDice(DiceRoller):
    def __init__(self) -> None:
        super().__init__(seed=1)

    def chance(self, probability: float) -> bool:
        return probability > 0

    def d6(self) -> int:
        return 6  # leadership fire check always fails → isolates the upgrade


def test_fire_suppression_extinguishes_in_end_phase() -> None:
    UpgradeRegistry.reset()
    state = GameState()
    state.dice = _AlwaysChanceDice()
    ship = build_ship_with_upgrades(
        "fs",
        "Fireproof",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["fire_suppression_system"],
        position=Vector2D(0, 0),
    )
    ship.fires = 2
    state.add_ship(ship)

    log = resolve_turn(state, {"fs": Command(ship_id="fs", action="pass", args={})})

    assert ship.fires == 1  # one fire suppressed by the upgrade
    assert any(isinstance(e, FireSuppressedByUpgradeEvent) for e in log.events)


def test_combustion_regen_bonus_applies() -> None:
    UpgradeRegistry.reset()
    state = GameState()
    ship = build_ship_with_upgrades(
        "ct",
        "Tanker",
        HULK_HULL,
        make_hulk_weapons(),
        upgrade_ids=["extended_combustion_tanks"],
        position=Vector2D(0, 0),
    )
    ship.combustion = 50
    state.add_ship(ship)

    resolve_turn(state, {"ct": Command(ship_id="ct", action="pass", args={})})

    assert ship.combustion == 50 + 15 + 5  # base 15 + upgrade bonus 5


def test_plain_ship_combustion_unchanged() -> None:
    state = GameState()
    ship = Ship.from_profile(
        "pl", "Plain", HULK_HULL, make_hulk_weapons(), position=Vector2D(0, 0)
    )
    ship.combustion = 50
    state.add_ship(ship)
    resolve_turn(state, {"pl": Command(ship_id="pl", action="pass", args={})})
    assert ship.combustion == 65
```

Caveat: `_AlwaysChanceDice.d6() == 6` also affects any other end-phase d6 use; if the leadership fire check passes on 6 for high-leadership hulls (`roll <= effective_leadership`), pick a hull with leadership < 6 (`dataclasses.replace(HULK_HULL, leadership=5)`) so only the upgrade extinguishes.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_battle.py -v`
Expected: FAIL — `ImportError: cannot import name 'FireSuppressedByUpgradeEvent'`

- [ ] **Step 3: Implement**

`upgrade_effects.py` (module level; `TurnEvent` import from `spacefleet.core.events`):

```python
@dataclasses.dataclass
class FireSuppressedByUpgradeEvent(TurnEvent):
    ship_id: str
    fires_remaining: int


def fire_extinguish_chance(ship: Ship) -> float:
    """Per-turn self-extinguish probability (fire suppression system)."""
    return float(upgrade_effect_total(ship.upgrade_ids, "fire_extinguish_chance"))
```

`turn_resolver.py` end phase — insert **before** the existing `# Fire extinguishing — leadership check` block:

```python
        # Fire suppression upgrade — chance to self-extinguish one fire
        if ship.fires > 0:
            from spacefleet.commander.upgrade_effects import (
                FireSuppressedByUpgradeEvent,
                fire_extinguish_chance,
            )

            suppress_p = fire_extinguish_chance(ship)
            if suppress_p > 0 and state.dice.chance(suppress_p):
                ship.fires = max(0, ship.fires - 1)
                emit(
                    FireSuppressedByUpgradeEvent(
                        ship_id=ship.id, fires_remaining=ship.fires
                    )
                )
```

And change the combustion line:

```python
        ship.regenerate_combustion(15 + ship.combustion_regen_bonus)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_battle.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/net/turn_resolver.py src/spacefleet/commander/upgrade_effects.py tests/test_upgrade_battle.py
git commit -m "feat(upgrades): fire suppression + combustion tanks in end phase"
```

---

## Task 10: Navigator's Chamber (flagship micro-warp charge)

**Files:**
- Modify: `src/spacefleet/commander/upgrade_effects.py`
- Modify: `src/spacefleet/net/game_state.py`
- Test: `tests/test_upgrade_effects.py` (append)

**Interfaces:**
- Consumes: `Commander.ability_state: dict[str, AbilityState]` with `remaining_charges`.
- Produces: `apply_flagship_upgrade_charges(commander: Commander, flagship: Ship) -> None`; wired into `_assign_default_commander` after the commander is built.

- [ ] **Step 1: Write the failing test** (append to `tests/test_upgrade_effects.py`)

```python
def test_navigators_chamber_adds_micro_warp_charge() -> None:
    UpgradeRegistry.reset()
    from spacefleet.commander.commander import AbilityState, Commander
    from spacefleet.commander.upgrade_effects import apply_flagship_upgrade_charges
    from spacefleet.core.types import Faction

    cmdr = Commander(id="c1", name="Cmdr", faction=Faction.IMPERIAL_NAVY)
    cmdr.ability_state["micro_warp_jump"] = AbilityState(remaining_charges=1)
    flagship = build_ship_with_upgrades(
        "fl", "Flag", HULK_HULL, make_hulk_weapons(), upgrade_ids=["navigators_chamber"]
    )
    apply_flagship_upgrade_charges(cmdr, flagship)
    assert cmdr.ability_state["micro_warp_jump"].remaining_charges == 2

    # No-ops: no upgrade / no such ability
    plain = Ship.from_profile("fl2", "Plain", HULK_HULL, make_hulk_weapons())
    apply_flagship_upgrade_charges(cmdr, plain)
    assert cmdr.ability_state["micro_warp_jump"].remaining_charges == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_upgrade_effects.py::test_navigators_chamber_adds_micro_warp_charge -v`
Expected: FAIL — `ImportError: cannot import name 'apply_flagship_upgrade_charges'`

- [ ] **Step 3: Implement**

`upgrade_effects.py` (TYPE_CHECKING import for `Commander`):

```python
def apply_flagship_upgrade_charges(commander: Commander, flagship: Ship) -> None:
    """Flagship-only ability-charge bonuses (Navigator's Chamber)."""
    bonus = int(upgrade_effect_total(flagship.upgrade_ids, "micro_warp_charges"))
    if bonus == 0:
        return
    ability = commander.ability_state.get("micro_warp_jump")
    if ability is not None:
        ability.remaining_charges += bonus
```

`net/game_state.py`, in `_assign_default_commander`, after `cmdr = _build_starter_commander(fleet_id, faction)`:

```python
    from spacefleet.commander.upgrade_effects import apply_flagship_upgrade_charges

    apply_flagship_upgrade_charges(cmdr, flagship)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_upgrade_effects.py -v`
Expected: PASS (all)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/commander/upgrade_effects.py src/spacefleet/net/game_state.py tests/test_upgrade_effects.py
git commit -m "feat(upgrades): navigators chamber grants flagship warp charge"
```

---

## Task 11: Integration battle test + docs

**Files:**
- Test: `tests/test_upgrade_battle.py` (append)
- Modify: `docs/docs/data/upgrade-catalog.md` (implementation-status note)

**Interfaces:**
- Consumes: everything above, through `resolve_turn`.

- [ ] **Step 1: Write the failing (or immediately passing — this is an integration seal) test**

```python
def test_upgraded_ship_full_turn_integration() -> None:
    """Turbo weaponry + shield capacitor + master of signals through resolve_turn."""
    UpgradeRegistry.reset()
    import dataclasses as dc

    from spacefleet.commander.passive_skills import (
        battery_firepower_bonus,
        end_of_turn_shield_regen,
    )
    from spacefleet.core.types import Faction, Stance

    state = GameState()
    shielded_hull = dc.replace(HULK_HULL, shields=4)
    ship = build_ship_with_upgrades(
        "int1",
        "Integrated",
        shielded_hull,
        make_hulk_weapons(),
        upgrade_ids=["turbo_weaponry", "auxiliary_shield_capacitor", "master_of_signals"],
        position=Vector2D(0, 0),
    )
    ship.shields_current = 1
    state.add_ship(ship)

    log = resolve_turn(state, {"int1": Command(ship_id="int1", action="pass", args={})})
    assert log is not None

    # Capacitor: base regen 1 + upgrade 1 = 2 → shields 1 → 3
    assert ship.shields_current == 3
    # Bus carries the turbo bonus after the turn's build
    assert battery_firepower_bonus(state, ship, ship, ship.weapons[0]) == 1
    assert end_of_turn_shield_regen(state, ship) == 1
    # Master of signals: cooldown 1 lower than the stance's configured cooldown
    from spacefleet.data.stance_registry import StanceRegistry

    ship.switch_stance(Stance.LOCK_ON)
    expected = max(0, StanceRegistry.get_for(Stance.LOCK_ON).switch_cooldown - 1)
    assert ship.stance_cooldown_remaining == expected
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, zero failures

- [ ] **Step 3: Docs note**

In `docs/docs/data/upgrade-catalog.md`, add under the intro paragraph:

```markdown
:::note Implementation status
All catalog upgrades are wired into battle except **Power Ram** (awaits a
ramming mechanic), and the torpedo-linked halves of **Extra Turrets** and
**Automated Reload System** (await Sprint-6 torpedoes — their stats/hooks
already load). Slot caps: Escort 1, Light Cruiser 2, Cruiser 3,
Battlecruiser 3, Battleship 4; Mechanicus Rites adds +1.
:::
```

- [ ] **Step 4: Final gate**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q`
Expected: all clean

- [ ] **Step 5: Commit**

```bash
git add tests/test_upgrade_battle.py docs/docs/data/upgrade-catalog.md
git commit -m "test(upgrades): full-turn integration + catalog status note"
```

---

## Self-Review (done at planning time)

- **Spec coverage:** all 20 upgrades map to Tasks 1–10 (hull stats T4, ship state T2/T4, bus T5, AP T6, lance crit T7, belt T8, fire/combustion T9, flagship T10, validation+Mechanicus T3, inert power_ram documented T11).
- **Type consistency:** `upgrade_effect_total(list[str], str) -> float` used everywhere; `LoadoutError` from `models.loadout`; event carries `ship_id: str` (not `Ship`) to keep the dataclass cheap — renderer can look the ship up.
- **Known risks flagged in-task:** `Projectile.distance_traveled` settability (T6), `_FixedDice(6)` interactions with 2d6 crit table (T7) and leadership checks (T9) — each has a guard note.
