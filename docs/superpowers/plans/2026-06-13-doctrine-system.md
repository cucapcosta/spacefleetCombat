# Doctrine System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-ship faction doctrines with all eight effects working in battle and at build time.

**Architecture:** A new `DoctrineRegistry` (yaml + fallback, mirroring `WeaponRegistry`); two new `Ship` fields (`doctrine_id`, `morale_floor`); a `commander/doctrine_effects.py` module that applies build-time stat mods and registers per-ship `PassiveBus` handlers; plus small strike-phase plumbing for assault bonus + boarding immunity. Reuses the Sprint-5 passive hooks (`HIT_COLUMN_SHIFT`, `LANCE_HIT_THRESHOLD`, `ASSAULT_ACTION_BONUS`, `ANTI_MUTINY_CHECK`).

**Tech Stack:** Python 3.12, uv, pytest, ruff, mypy --strict.

**Spec:** `docs/superpowers/specs/2026-06-13-doctrine-system-design.md`

---

## File Structure

- **Create** `data/doctrines/doctrines.yaml` — the 8 doctrine definitions.
- **Create** `src/spacefleet/data/doctrine_registry.py` — `DoctrineDef` + `DoctrineRegistry`.
- **Modify** `src/spacefleet/data/__init__.py` — export `DoctrineRegistry`.
- **Modify** `src/spacefleet/models/ship.py` — add `doctrine_id`, `morale_floor`; floor clamp in `apply_morale_change`; `from_profile` passthrough.
- **Create** `src/spacefleet/commander/doctrine_effects.py` — `apply_doctrine_to_hull`, `build_ship_with_doctrine`, `register_doctrine_handlers`, `doctrine_allows_weapon`, `BoardingRepelledByDoctrineEvent`.
- **Modify** `src/spacefleet/commander/passive_skills.py` — `assault_action_bonus` helper; call `register_doctrine_handlers` from `PassiveBus.build` (local import).
- **Modify** `src/spacefleet/net/turn_resolver.py` — strike phase: assault bonus + boarding immunity.
- **Create** tests: `tests/test_doctrine_registry.py`, `tests/test_doctrine_effects.py`, `tests/test_doctrine_battle.py`.

## Reference: existing APIs (verified)

- `WeaponRegistry` pattern: class attrs `_items`/`_loaded`; `@classmethod _load(cls)` guarded by `_loaded`; `_load_demo_fallback`; `get`, `get_or_none`, `all`, `reset`. `get`/`all` call `cls._load()` first. Imports `from spacefleet.data.loader import YAML_AVAILABLE, get_data_dir, load_yaml_file`.
- `load_yaml_file(path) -> dict | None`; `get_data_dir() -> Path | None`.
- `Ship` is a dataclass; all fields after `shields_current` have defaults. `Ship.from_profile(ship_id, name, hull, weapons, *, position=None, heading=0.0, speed=0.0)` builds via `cls(...)`.
- `Ship.apply_morale_change` currently ends: `self.morale = max(0, min(self.morale_max, self.morale + effective_delta))`.
- `HullProfile` is a frozen dataclass with int `hull_hits`, float `speed`, int `shields`. Use `dataclasses.replace`.
- `Faction` enum: `Faction.IMPERIAL_NAVY` (`.value == "imperial_navy"`), `Faction.CHAOS_FLEET` (`"chaos_fleet"`).
- `PassiveBus.build(state)` calls `_register_*` helpers then returns the bus. `PassiveHook` has `HIT_COLUMN_SHIFT`, `LANCE_HIT_THRESHOLD`, `ASSAULT_ACTION_BONUS`, `ANTI_MUTINY_CHECK`. Public helpers exist: `hit_column_shift`, `lance_hit_threshold`, `anti_mutiny_suppressed` (no `assault_action_bonus` yet).
- `turn_resolver` strike loop (~line 304-335): finds `target`, checks alive + within 15 GU + `target.shields_current == 0`, then `assault_actions = ship.hull.assault_actions`; `if assault_actions <= 0: continue`; `resolve_boarding(...)`; `apply_boarding_result(...)`; `emit(LightningStrikeEvent(...))`.
- `WeaponType` enum has `LANCE` and `BATTERY`; `WeaponProfile.weapon_type`.

---

## Task 1: DoctrineDef + DoctrineRegistry + data + export

**Files:**
- Create: `data/doctrines/doctrines.yaml`
- Create: `src/spacefleet/data/doctrine_registry.py`
- Modify: `src/spacefleet/data/__init__.py`
- Test: `tests/test_doctrine_registry.py`

- [ ] **Step 1: Write the failing test**

```python
"""DoctrineRegistry — load the 8 faction doctrines."""

from __future__ import annotations

from spacefleet.core.types import Faction
from spacefleet.data import DoctrineRegistry


def test_loads_all_eight_doctrines() -> None:
    DoctrineRegistry.reset()
    ids = set(DoctrineRegistry.all().keys())
    assert ids == {
        "navy_gunnery_school",
        "commissariat",
        "space_marine_detachment",
        "mechanicus_rites",
        "mark_of_khorne",
        "mark_of_tzeentch",
        "mark_of_nurgle",
        "mark_of_slaanesh",
    }


def test_for_faction_filters() -> None:
    DoctrineRegistry.reset()
    imp = {d.id for d in DoctrineRegistry.for_faction(Faction.IMPERIAL_NAVY)}
    cha = {d.id for d in DoctrineRegistry.for_faction(Faction.CHAOS_FLEET)}
    assert "navy_gunnery_school" in imp and "mark_of_khorne" not in imp
    assert "mark_of_khorne" in cha and "navy_gunnery_school" not in cha


def test_effect_fields() -> None:
    DoctrineRegistry.reset()
    nurgle = DoctrineRegistry.get("mark_of_nurgle")
    assert nurgle.hull_delta == 2 and nurgle.speed_delta == -5.0
    tzeentch = DoctrineRegistry.get("mark_of_tzeentch")
    assert tzeentch.lance_threshold == 3 and tzeentch.hull_delta == -1
    khorne = DoctrineRegistry.get("mark_of_khorne")
    assert khorne.assault_bonus == 3 and khorne.lances_allowed is False
    sm = DoctrineRegistry.get("space_marine_detachment")
    assert sm.assault_bonus == 2 and sm.board_immune is True
    assert DoctrineRegistry.get("commissariat").morale_floor == 20
    assert DoctrineRegistry.get("navy_gunnery_school").column_shift == 1
    assert DoctrineRegistry.get("mechanicus_rites").upgrade_slot_bonus == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_doctrine_registry.py -q`
Expected: FAIL — `cannot import name 'DoctrineRegistry' from 'spacefleet.data'`.

- [ ] **Step 3: Create `data/doctrines/doctrines.yaml`**

```yaml
doctrines:
  navy_gunnery_school:
    name: "Navy Gunnery School"
    faction: imperial_navy
    cost: 15
    description: "All batteries on this ship gain +1 gunnery column shift."
    column_shift: 1
  commissariat:
    name: "Commissariat"
    faction: imperial_navy
    cost: 15
    description: "Ship cannot mutiny. Morale cannot drop below 20."
    morale_floor: 20
  space_marine_detachment:
    name: "Space Marine Detachment"
    faction: imperial_navy
    cost: 25
    description: "+2 boarding assault actions. Immune to enemy boarding."
    assault_bonus: 2
    board_immune: true
  mechanicus_rites:
    name: "Mechanicus Rites"
    faction: imperial_navy
    cost: 20
    description: "+1 upgrade slot on this ship."
    upgrade_slot_bonus: 1
  mark_of_khorne:
    name: "Mark of Khorne"
    faction: chaos_fleet
    cost: 25
    description: "+3 boarding assault actions. Cannot use lances."
    assault_bonus: 3
    lances_allowed: false
  mark_of_tzeentch:
    name: "Mark of Tzeentch"
    faction: chaos_fleet
    cost: 25
    description: "Lance hits on 3+ instead of 4+. -1 hull."
    lance_threshold: 3
    hull_delta: -1
  mark_of_nurgle:
    name: "Mark of Nurgle"
    faction: chaos_fleet
    cost: 15
    description: "+2 hull. -5 speed."
    hull_delta: 2
    speed_delta: -5
  mark_of_slaanesh:
    name: "Mark of Slaanesh"
    faction: chaos_fleet
    cost: 15
    description: "+10 speed. -1 shield."
    speed_delta: 10
    shield_delta: -1
```

- [ ] **Step 4: Create `src/spacefleet/data/doctrine_registry.py`**

```python
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
            DoctrineDef("navy_gunnery_school", "Navy Gunnery School", "imperial_navy", 15,
                        column_shift=1),
            DoctrineDef("commissariat", "Commissariat", "imperial_navy", 15, morale_floor=20),
            DoctrineDef("space_marine_detachment", "Space Marine Detachment", "imperial_navy",
                        25, assault_bonus=2, board_immune=True),
            DoctrineDef("mechanicus_rites", "Mechanicus Rites", "imperial_navy", 20,
                        upgrade_slot_bonus=1),
            DoctrineDef("mark_of_khorne", "Mark of Khorne", "chaos_fleet", 25,
                        assault_bonus=3, lances_allowed=False),
            DoctrineDef("mark_of_tzeentch", "Mark of Tzeentch", "chaos_fleet", 25,
                        lance_threshold=3, hull_delta=-1),
            DoctrineDef("mark_of_nurgle", "Mark of Nurgle", "chaos_fleet", 15,
                        hull_delta=2, speed_delta=-5.0),
            DoctrineDef("mark_of_slaanesh", "Mark of Slaanesh", "chaos_fleet", 15,
                        speed_delta=10.0, shield_delta=-1),
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
```

- [ ] **Step 5: Export from `data/__init__.py`**

Replace the file body with:

```python
"""Data layer — YAML-backed registries with inline demo fallback."""

from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.weapon_registry import WeaponRegistry

__all__ = ["DoctrineRegistry", "HullRegistry", "WeaponRegistry"]
```

- [ ] **Step 6: Run test + gate + commit**

Run: `uv run pytest tests/test_doctrine_registry.py -q` → PASS (3 tests).
Then:
```bash
uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src
git add data/doctrines/doctrines.yaml src/spacefleet/data/doctrine_registry.py src/spacefleet/data/__init__.py tests/test_doctrine_registry.py
git commit -m "feat(data): doctrine registry + 8 faction doctrines"
```

---

## Task 2: Ship.doctrine_id + morale_floor + floor clamp

**Files:**
- Modify: `src/spacefleet/models/ship.py`
- Test: `tests/test_doctrine_effects.py`

- [ ] **Step 1: Write the failing test**

```python
"""Doctrine effects — build-time stat mods, handlers, validation."""

from __future__ import annotations

import dataclasses

from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.ship import Ship


def test_morale_floor_clamps_losses() -> None:
    s = Ship.from_profile(
        "s", "S", HULK_HULL, make_hulk_weapons(), morale_floor=20
    )
    s.apply_morale_change(-1000)
    assert s.morale == 20


def test_default_floor_is_zero() -> None:
    s = Ship.from_profile("s", "S", HULK_HULL, make_hulk_weapons())
    assert s.morale_floor == 0
    assert s.doctrine_id is None
    s.apply_morale_change(-1000)
    assert s.morale == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_doctrine_effects.py -q`
Expected: FAIL — `from_profile()` got an unexpected keyword argument `morale_floor`.

- [ ] **Step 3: Add fields + clamp + passthrough**

In `src/spacefleet/models/ship.py`, add two fields at the END of the dataclass field list (immediately after the crew-veterancy `battles_survived` field, before any methods):

```python
    # ── doctrine ──
    doctrine_id: str | None = None
    morale_floor: int = 0
```

Change the final line of `apply_morale_change` from:

```python
        self.morale = max(0, min(self.morale_max, self.morale + effective_delta))
```

to:

```python
        self.morale = max(self.morale_floor, min(self.morale_max, self.morale + effective_delta))
```

In `from_profile`, add two keyword params and pass them through. Change the signature:

```python
        position: Vector2D | None = None,
        heading: float = 0.0,
        speed: float = 0.0,
        doctrine_id: str | None = None,
        morale_floor: int = 0,
    ) -> Ship:
```

and add to the `cls(...)` construction (alongside `morale=...`):

```python
            doctrine_id=doctrine_id,
            morale_floor=morale_floor,
```

- [ ] **Step 4: Run test + gate**

Run: `uv run pytest tests/test_doctrine_effects.py -q` → PASS (2).
`uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src && uv run pytest -q` → all green (248 total).

- [ ] **Step 5: Commit**

```bash
git add src/spacefleet/models/ship.py tests/test_doctrine_effects.py
git commit -m "feat(ship): doctrine_id + morale_floor fields with floor-clamped morale"
```

---

## Task 3: apply_doctrine_to_hull + build_ship_with_doctrine

**Files:**
- Create: `src/spacefleet/commander/doctrine_effects.py`
- Test: `tests/test_doctrine_effects.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_doctrine_effects.py`)**

```python
from spacefleet.commander.doctrine_effects import (
    apply_doctrine_to_hull,
    build_ship_with_doctrine,
)
from spacefleet.data.doctrine_registry import DoctrineRegistry


def test_apply_stat_mods_nurgle() -> None:
    base = HULK_HULL
    nurgle = DoctrineRegistry.get("mark_of_nurgle")
    modded = apply_doctrine_to_hull(base, nurgle)
    assert modded.hull_hits == base.hull_hits + 2
    assert modded.speed == base.speed - 5.0


def test_apply_stat_mods_clamps_minimums() -> None:
    # HULK speed is 0; Nurgle -5 must clamp to 0, not go negative.
    modded = apply_doctrine_to_hull(HULK_HULL, DoctrineRegistry.get("mark_of_nurgle"))
    assert modded.speed >= 0.0


def test_build_ship_applies_doctrine() -> None:
    ship = build_ship_with_doctrine(
        "s", "S", HULK_HULL, make_hulk_weapons(),
        doctrine_id="commissariat",
    )
    assert ship.doctrine_id == "commissariat"
    assert ship.morale_floor == 20


def test_build_ship_none_doctrine_is_plain() -> None:
    ship = build_ship_with_doctrine(
        "s", "S", HULK_HULL, make_hulk_weapons(), doctrine_id=None
    )
    assert ship.doctrine_id is None and ship.morale_floor == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_doctrine_effects.py -q`
Expected: FAIL — `No module named 'spacefleet.commander.doctrine_effects'`.

- [ ] **Step 3: Create `src/spacefleet/commander/doctrine_effects.py`**

```python
"""Doctrine effects — build-time stat mods, runtime PassiveBus handlers,
and build-time validation helpers."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from spacefleet.commander.passive_skills import PassiveContext, PassiveHook
from spacefleet.core.events import TurnEvent
from spacefleet.core.types import WeaponType
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.models.ship import Ship

if TYPE_CHECKING:
    from spacefleet.commander.passive_skills import PassiveBus
    from spacefleet.core.game_state import CoreGameState
    from spacefleet.core.types import Vector2D
    from spacefleet.data.doctrine_registry import DoctrineDef
    from spacefleet.models.ship_profile import HullProfile
    from spacefleet.models.weapon import WeaponMount, WeaponProfile


@dataclasses.dataclass
class BoardingRepelledByDoctrineEvent(TurnEvent):
    attacker_id: str
    target_id: str


def apply_doctrine_to_hull(hull: HullProfile, doctrine: DoctrineDef) -> HullProfile:
    """Hull copy with the doctrine's stat deltas applied; clamp hull_hits>=1,
    shields>=0, speed>=0.0."""
    return dataclasses.replace(
        hull,
        hull_hits=max(1, hull.hull_hits + doctrine.hull_delta),
        speed=max(0.0, hull.speed + doctrine.speed_delta),
        shields=max(0, hull.shields + doctrine.shield_delta),
    )


def build_ship_with_doctrine(
    ship_id: str,
    name: str,
    hull: HullProfile,
    weapons: list[WeaponMount],
    *,
    doctrine_id: str | None,
    position: Vector2D | None = None,
    heading: float = 0.0,
) -> Ship:
    """Construct a Ship applying its doctrine (stat-modded hull + doctrine_id +
    morale_floor). ``doctrine_id=None`` builds a plain ship."""
    doctrine = DoctrineRegistry.get_or_none(doctrine_id)
    final_hull = apply_doctrine_to_hull(hull, doctrine) if doctrine is not None else hull
    floor = doctrine.morale_floor if doctrine is not None else 0
    return Ship.from_profile(
        ship_id,
        name,
        final_hull,
        weapons,
        position=position,
        heading=heading,
        doctrine_id=doctrine_id,
        morale_floor=floor,
    )


def doctrine_allows_weapon(doctrine: DoctrineDef, weapon: WeaponProfile) -> bool:
    """False when the doctrine bans this weapon (Khorne bans lances)."""
    if not doctrine.lances_allowed and weapon.weapon_type == WeaponType.LANCE:
        return False
    return True


def register_doctrine_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Per-ship PassiveBus handlers keyed on ``ship.doctrine_id``."""
    for ship in state.ships.values():
        doctrine = DoctrineRegistry.get_or_none(ship.doctrine_id)
        if doctrine is None:
            continue
        sid = ship.id

        if doctrine.column_shift:

            def _col(ctx: PassiveContext, s: str = sid, v: int = doctrine.column_shift) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:doctrine_column",
                hook=PassiveHook.HIT_COLUMN_SHIFT,
                handler=_col,
            )

        if doctrine.lance_threshold is not None:
            lt = doctrine.lance_threshold  # bind narrowed int (mypy: avoid int|None default)

            def _lance(ctx: PassiveContext, s: str = sid, t: int = lt) -> Any:
                return t if ctx.ship is not None and ctx.ship.id == s else None

            bus.register(
                source=f"{sid}:doctrine_lance",
                hook=PassiveHook.LANCE_HIT_THRESHOLD,
                handler=_lance,
            )

        if doctrine.assault_bonus:

            def _assault(ctx: PassiveContext, s: str = sid, v: int = doctrine.assault_bonus) -> Any:
                return ctx.value + v if ctx.ship is not None and ctx.ship.id == s else ctx.value

            bus.register(
                source=f"{sid}:doctrine_assault",
                hook=PassiveHook.ASSAULT_ACTION_BONUS,
                handler=_assault,
            )

        if doctrine.morale_floor > 0:

            def _nomutiny(ctx: PassiveContext, s: str = sid) -> Any:
                return True if ctx.ship is not None and ctx.ship.id == s else None

            bus.register(
                source=f"{sid}:doctrine_nomutiny",
                hook=PassiveHook.ANTI_MUTINY_CHECK,
                handler=_nomutiny,
            )
```

- [ ] **Step 4: Run test + gate**

Run: `uv run pytest tests/test_doctrine_effects.py -q` → PASS.
`uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src` → clean.

> Note: `WeaponProfile`/`Vector2D` are only used in type annotations, so they live in
> the `TYPE_CHECKING` block. `Ship` and the passive types are used at runtime.

- [ ] **Step 5: Commit**

```bash
git add src/spacefleet/commander/doctrine_effects.py tests/test_doctrine_effects.py
git commit -m "feat(doctrine): hull stat-mods, doctrine ship builder, validation + handlers"
```

---

## Task 4: Wire register_doctrine_handlers into PassiveBus + column/lance tests

**Files:**
- Modify: `src/spacefleet/commander/passive_skills.py`
- Test: `tests/test_doctrine_effects.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from spacefleet.commander.passive_skills import (
    PassiveBus,
    hit_column_shift,
    lance_hit_threshold,
)
from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D


def _state_with_doctrine(doctrine_id: str, faction: Faction) -> tuple[CoreGameState, Ship, Ship]:
    state = CoreGameState()
    ship = build_ship_with_doctrine(
        "s", "S", HULK_HULL, make_hulk_weapons(),
        doctrine_id=doctrine_id, position=Vector2D(0, 0),
    )
    ship.faction = faction
    enemy = Ship.from_profile("e", "E", HULK_HULL, make_hulk_weapons(), position=Vector2D(2, 0))
    enemy.faction = Faction.CHAOS_FLEET if faction == Faction.IMPERIAL_NAVY else Faction.IMPERIAL_NAVY
    state.add_ship(ship)
    state.add_ship(enemy)
    state.passives = PassiveBus.build(state)
    return state, ship, enemy


def test_navy_gunnery_column_shift() -> None:
    state, ship, enemy = _state_with_doctrine("navy_gunnery_school", Faction.IMPERIAL_NAVY)
    assert hit_column_shift(state, ship, enemy, ship.weapons[0]) == 1


def test_tzeentch_lance_threshold() -> None:
    state, ship, _ = _state_with_doctrine("mark_of_tzeentch", Faction.CHAOS_FLEET)
    assert lance_hit_threshold(state, ship) == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_doctrine_effects.py -k "column_shift or lance_threshold" -q`
Expected: FAIL — column shift is 0 / threshold is 4 (handlers not registered).

- [ ] **Step 3: Call register_doctrine_handlers from PassiveBus.build**

In `src/spacefleet/commander/passive_skills.py`, inside `PassiveBus.build`, after the existing `_register_crew_tier_handlers(bus, state)` line and before `return bus`, add:

```python
        from spacefleet.commander.doctrine_effects import register_doctrine_handlers

        register_doctrine_handlers(bus, state)
```

> The import is function-local to avoid a module-load import cycle
> (`doctrine_effects` imports `passive_skills` at module top).

- [ ] **Step 4: Run test + gate**

Run: `uv run pytest tests/test_doctrine_effects.py -q` → PASS.
`uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src && uv run pytest -q` → all green.

- [ ] **Step 5: Commit**

```bash
git add src/spacefleet/commander/passive_skills.py tests/test_doctrine_effects.py
git commit -m "feat(doctrine): register per-ship doctrine handlers on the passive bus"
```

---

## Task 5: assault_action_bonus helper + thread into strike phase

**Files:**
- Modify: `src/spacefleet/commander/passive_skills.py`
- Modify: `src/spacefleet/net/turn_resolver.py`
- Test: `tests/test_doctrine_effects.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from spacefleet.commander.passive_skills import assault_action_bonus


def test_space_marine_assault_bonus() -> None:
    state, ship, _ = _state_with_doctrine("space_marine_detachment", Faction.IMPERIAL_NAVY)
    assert assault_action_bonus(state, ship) == 2


def test_khorne_assault_bonus() -> None:
    state, ship, _ = _state_with_doctrine("mark_of_khorne", Faction.CHAOS_FLEET)
    assert assault_action_bonus(state, ship) == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_doctrine_effects.py -k assault -q`
Expected: FAIL — `cannot import name 'assault_action_bonus'`.

- [ ] **Step 3: Add the helper to `passive_skills.py`**

Append next to the other public dispatch helpers (e.g. after `anti_mutiny_suppressed`):

```python
def assault_action_bonus(state: CoreGameState, ship: Ship) -> int:
    passives = getattr(state, "passives", None)
    if passives is None:
        return 0
    ctx = PassiveContext(ship=ship, fleet=state.fleet_of(ship), state=state, value=0)
    return int(passives.dispatch(PassiveHook.ASSAULT_ACTION_BONUS, ctx))
```

- [ ] **Step 4: Thread it into the strike sub-phase**

In `src/spacefleet/net/turn_resolver.py`, find the strike-phase line:

```python
        assault_actions = ship.hull.assault_actions
```

Replace with:

```python
        from spacefleet.commander.passive_skills import assault_action_bonus

        assault_actions = ship.hull.assault_actions + assault_action_bonus(state, ship)
```

- [ ] **Step 5: Run test + gate + commit**

Run: `uv run pytest tests/test_doctrine_effects.py -q` → PASS.
`uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src && uv run pytest -q` → green.
```bash
git add src/spacefleet/commander/passive_skills.py src/spacefleet/net/turn_resolver.py tests/test_doctrine_effects.py
git commit -m "feat(doctrine): assault-action bonus helper wired into the strike phase"
```

---

## Task 6: Boarding immunity in the strike phase

**Files:**
- Modify: `src/spacefleet/net/turn_resolver.py`
- Test: `tests/test_doctrine_battle.py`

- [ ] **Step 1: Write the failing test**

```python
"""Doctrine effects exercised through resolve_turn."""

from __future__ import annotations

import dataclasses

from spacefleet.commander.doctrine_effects import (
    BoardingRepelledByDoctrineEvent,
    build_ship_with_doctrine,
)
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.models.ship import Ship
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import resolve_turn


def test_space_marine_repels_boarding() -> None:
    state = GameState()
    # Attacker with assault capability, adjacent to a board-immune Space Marine ship.
    attacker_hull = dataclasses.replace(HULK_HULL, assault_actions=3)
    attacker = Ship.from_profile(
        "boarder", "Boarder", attacker_hull, make_hulk_weapons(), position=Vector2D(0, 0)
    )
    attacker.faction = Faction.CHAOS_FLEET
    target = build_ship_with_doctrine(
        "marine", "Marine", HULK_HULL, make_hulk_weapons(),
        doctrine_id="space_marine_detachment", position=Vector2D(0, 0),
    )
    target.faction = Faction.IMPERIAL_NAVY
    target.shields_current = 0  # boardable
    state.add_ship(attacker)
    state.add_ship(target)

    strike = Command(ship_id="boarder", action="strike", args={"target": "marine"})
    log = resolve_turn(state, {"boarder": strike})

    assert any(isinstance(e, BoardingRepelledByDoctrineEvent) for e in log.events)
    assert target.morale == target.morale_max  # took no boarding morale damage
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_doctrine_battle.py -q`
Expected: FAIL — no `BoardingRepelledByDoctrineEvent`; boarding resolves normally.

- [ ] **Step 3: Add the immunity check in the strike loop**

In `turn_resolver.py`, in the strike loop, immediately AFTER the shields check
(`if target.shields_current > 0: continue`) and BEFORE the
`from spacefleet.combat.boarding import (...)` block, insert:

```python
        from spacefleet.data.doctrine_registry import DoctrineRegistry

        t_doc = DoctrineRegistry.get_or_none(target.doctrine_id)
        if t_doc is not None and t_doc.board_immune:
            from spacefleet.commander.doctrine_effects import (
                BoardingRepelledByDoctrineEvent,
            )

            emit(BoardingRepelledByDoctrineEvent(attacker_id=ship.id, target_id=target.id))
            continue
```

- [ ] **Step 4: Run test + gate + commit**

Run: `uv run pytest tests/test_doctrine_battle.py -q` → PASS.
`uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src && uv run pytest -q` → green.
```bash
git add src/spacefleet/net/turn_resolver.py tests/test_doctrine_battle.py
git commit -m "feat(doctrine): Space Marine Detachment repels enemy boarding"
```

---

## Task 7: Khorne lance-ban validation helper

**Files:**
- Test: `tests/test_doctrine_effects.py` (helper already implemented in Task 3)

- [ ] **Step 1: Write the test (append)**

```python
from spacefleet.commander.doctrine_effects import doctrine_allows_weapon
from spacefleet.data.demo_data import SALVAGE_GUN
from spacefleet.data.weapon_registry import WeaponRegistry


def test_khorne_bans_lances() -> None:
    khorne = DoctrineRegistry.get("mark_of_khorne")
    # SALVAGE_GUN is a BATTERY → allowed.
    assert doctrine_allows_weapon(khorne, SALVAGE_GUN) is True
    # Find any lance in the weapon catalog → banned.
    lances = [
        w for w in WeaponRegistry.all().values()
        if w.weapon_type.value == "lance"
    ]
    assert lances, "expected at least one lance in the catalog"
    assert doctrine_allows_weapon(khorne, lances[0]) is False


def test_non_khorne_allows_lances() -> None:
    tzeentch = DoctrineRegistry.get("mark_of_tzeentch")
    lances = [w for w in WeaponRegistry.all().values() if w.weapon_type.value == "lance"]
    assert doctrine_allows_weapon(tzeentch, lances[0]) is True
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_doctrine_effects.py -k khorne_bans -q`
Expected: PASS (`doctrine_allows_weapon` implemented in Task 3).

> If `WeaponRegistry.all()` contains no lance, the test asserts will fail loudly on
> the `assert lances` line — that means the weapon catalog has no lance weapon;
> in that case construct a lance `WeaponProfile` inline with
> `WeaponType.LANCE` to exercise the helper rather than pulling from the catalog.

- [ ] **Step 3: Commit**

```bash
git add tests/test_doctrine_effects.py
git commit -m "test(doctrine): Khorne lance-ban validation helper"
```

---

## Task 8: Commissariat morale floor through a real battle

**Files:**
- Test: `tests/test_doctrine_battle.py`

- [ ] **Step 1: Write the test (append)**

```python
def test_commissariat_holds_morale_floor() -> None:
    state = GameState()
    ship = build_ship_with_doctrine(
        "comm", "Commissar", HULK_HULL, make_hulk_weapons(),
        doctrine_id="commissariat", position=Vector2D(0, 0),
    )
    ship.faction = Faction.IMPERIAL_NAVY
    state.add_ship(ship)
    from spacefleet.commander.passive_skills import PassiveBus

    state.passives = PassiveBus.build(state)

    # Hammer morale far below the floor via the doctrine-aware path.
    ship.apply_morale_change(-1000, state=state)
    assert ship.morale == 20  # floor held

    # And it never mutinies at end-of-turn (anti-mutiny doctrine handler).
    from spacefleet.commander.passive_skills import anti_mutiny_suppressed

    ship.morale = 0  # force the mutiny gate
    assert anti_mutiny_suppressed(state, ship) is True
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/test_doctrine_battle.py::test_commissariat_holds_morale_floor -q`
Expected: PASS (floor clamp from Task 2 + anti-mutiny handler from Task 3/4).

> If it FAILS on the floor assert, confirm Task 2's clamp uses `self.morale_floor`
> and that `build_ship_with_doctrine` set `morale_floor=20` for Commissariat.

- [ ] **Step 3: Commit**

```bash
git add tests/test_doctrine_battle.py
git commit -m "test(doctrine): Commissariat morale floor + no-mutiny in battle"
```

---

## Task 9: Regression gate

- [ ] **Step 1: Full gate**

Run:
```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest -q
```
Expected: all clean; full suite green (246 prior + new doctrine tests). The two new
`Ship` fields default to no-op, so nothing pre-existing regresses.

- [ ] **Step 2: No commit** — verification only. If any gap, add a follow-up task, fix, re-run.
