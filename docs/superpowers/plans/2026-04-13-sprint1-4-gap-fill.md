# Sprint 1–4 Gap Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the modules listed in `docs/docs/architecture/implementation-roadmap.md` for sprints 1–4 that are not yet present in the codebase, plus the missing functional behaviour they imply (loadout slot validation, combustion spending, fleet container, phase resolvers, event bus).

**Architecture:** The codebase already implements the *behaviour* for most of sprint 1–4 inline in `models/ship.py`, `combat/resolution.py`, and `net/turn_resolver.py`. The roadmap calls for the same behaviour split into focused modules. The plan extracts pure helpers into the missing files (`models/loadout.py`, `models/morale.py`, `models/subsystems.py`, `models/stance.py`, `combat/gunnery.py`, `combat/lance.py`, `combat/damage.py`, `combat/morale_effects.py`, `spatial/movement.py`, `phases/movement_phase.py`, `phases/shooting_phase.py`, `core/game_state.py`, `core/events.py`, `data/upgrade_registry.py`, `models/fleet.py`) and re-exports from the existing modules so the runtime stays backwards compatible. Net effect: the existing `combat/resolution.py` and `net/turn_resolver.py` keep working unchanged, but the new modules become the canonical home for each concern and pick up new tests.

**Tech Stack:** Python 3.12, dataclasses, PyYAML (optional), pytest, ruff, mypy --strict.

---

## Conventions every task follows

- All new modules: `from __future__ import annotations` at top.
- Pure functions where possible; mutate `Ship` only via existing methods.
- No new dependencies.
- Every task ends with `pytest -q`, `ruff check src tests`, `mypy --strict src` all green before commit.
- Commits use Conventional Commits (`feat:`, `refactor:`, `test:`).

---

## File map

**Create:**
- `src/spacefleet/models/loadout.py`
- `src/spacefleet/models/fleet.py`
- `src/spacefleet/models/morale.py`
- `src/spacefleet/models/subsystems.py`
- `src/spacefleet/models/stance.py`
- `src/spacefleet/data/upgrade_registry.py`
- `src/spacefleet/spatial/movement.py`
- `src/spacefleet/phases/movement_phase.py`
- `src/spacefleet/phases/shooting_phase.py`
- `src/spacefleet/combat/gunnery.py`
- `src/spacefleet/combat/lance.py`
- `src/spacefleet/combat/damage.py`
- `src/spacefleet/combat/morale_effects.py`
- `src/spacefleet/core/game_state.py`
- `src/spacefleet/core/events.py`
- `tests/test_loadout.py`
- `tests/test_upgrade_registry.py`
- `tests/test_fleet.py`
- `tests/test_morale.py`
- `tests/test_subsystems.py`
- `tests/test_stance_module.py`
- `tests/test_movement.py`
- `tests/test_movement_phase.py`
- `tests/test_gunnery.py`
- `tests/test_lance.py`
- `tests/test_damage.py`
- `tests/test_morale_effects.py`
- `tests/test_shooting_phase.py`
- `tests/test_core_game_state.py`
- `tests/test_events.py`

**Modify:**
- `src/spacefleet/combat/resolution.py` — re-export from new modules
- `src/spacefleet/models/ship.py` — delegate state-bracket helpers to new pure modules
- `src/spacefleet/net/game_state.py` — base on `core.game_state.GameState`

---

# Sprint 1 Gap Fill

## Task 1: Loadout dataclass + slot validation

**Files:**
- Create: `src/spacefleet/models/loadout.py`
- Create: `tests/test_loadout.py`

- [ ] **Step 1: Write failing test**

`tests/test_loadout.py`:
```python
"""Tests for Loadout slot validation."""
from __future__ import annotations

import pytest

from spacefleet.core.types import Arc, WeaponSize, WeaponType
from spacefleet.models.loadout import Loadout, LoadoutError
from spacefleet.models.ship_profile import HullProfile, WeaponSlotDef
from spacefleet.models.weapon import WeaponMount, WeaponProfile
from spacefleet.core.types import Faction, ShipClass


def _hull(slot: WeaponSlotDef) -> HullProfile:
    return HullProfile(
        id="test_hull",
        name="Test",
        classification=ShipClass.LIGHT_CRUISER,
        faction=Faction.IMPERIAL_NAVY,
        hull_cost=100,
        leadership=8,
        hull_hits=6,
        armor_prow=6, armor_port=5, armor_starboard=5, armor_stern=4,
        speed=20.0, turn_rate=45.0,
        shields=2, turrets=1, sensor_range=40.0,
        weapon_slots=(slot,),
    )


def _weapon(*, wtype: WeaponType, size: WeaponSize) -> WeaponProfile:
    return WeaponProfile(
        id="w", name="W", weapon_type=wtype, size=size,
        strength=4, range=30.0, cost=10,
    )


def test_valid_loadout_passes():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=1, slot_name="Prow", arc=Arc.PROW, weapon=wp)
    lo = Loadout(weapons=[mount])
    lo.validate(hull)  # must not raise


def test_disallowed_type_raises():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.LANCE, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=1, slot_name="Prow", arc=Arc.PROW, weapon=wp)
    with pytest.raises(LoadoutError, match="not allowed"):
        Loadout(weapons=[mount]).validate(hull)


def test_size_too_large_raises():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.SMALL,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.LARGE)
    mount = WeaponMount(slot_id=1, slot_name="Prow", arc=Arc.PROW, weapon=wp)
    with pytest.raises(LoadoutError, match="too large"):
        Loadout(weapons=[mount]).validate(hull)


def test_unknown_slot_raises():
    slot = WeaponSlotDef(
        id=1, name="Prow", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    hull = _hull(slot)
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=99, slot_name="Ghost", arc=Arc.PROW, weapon=wp)
    with pytest.raises(LoadoutError, match="unknown slot"):
        Loadout(weapons=[mount]).validate(hull)


def test_total_cost():
    slot = WeaponSlotDef(
        id=1, name="P", arc=Arc.PROW,
        size=WeaponSize.MEDIUM,
        allowed_types=(WeaponType.BATTERY,),
    )
    wp = _weapon(wtype=WeaponType.BATTERY, size=WeaponSize.MEDIUM)
    mount = WeaponMount(slot_id=1, slot_name="P", arc=Arc.PROW, weapon=wp)
    assert Loadout(weapons=[mount]).total_cost() == 10
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_loadout.py -v`
Expected: FAIL — `ModuleNotFoundError: spacefleet.models.loadout`

- [ ] **Step 3: Implement `models/loadout.py`**

```python
"""Weapon + upgrade loadout container with slot validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.core.types import WeaponSize

if TYPE_CHECKING:
    from spacefleet.models.ship_profile import HullProfile
    from spacefleet.models.weapon import WeaponMount


class LoadoutError(ValueError):
    """Raised when a Loadout fails to validate against a HullProfile."""


_SIZE_ORDER: dict[WeaponSize, int] = {
    WeaponSize.SMALL: 1,
    WeaponSize.MEDIUM: 2,
    WeaponSize.LARGE: 3,
    WeaponSize.TORPEDO: 2,
    WeaponSize.SPECIAL: 2,
}


@dataclass
class Loadout:
    """A set of weapons (and, eventually, upgrades + doctrine) for a hull."""

    weapons: list[WeaponMount] = field(default_factory=list)
    upgrade_ids: list[str] = field(default_factory=list)
    doctrine_id: str | None = None

    def validate(self, hull: HullProfile) -> None:
        """Raise :class:`LoadoutError` if any mount is illegal for *hull*."""
        slot_index = {s.id: s for s in hull.weapon_slots}
        for mount in self.weapons:
            slot = slot_index.get(mount.slot_id)
            if slot is None:
                raise LoadoutError(
                    f"unknown slot id {mount.slot_id} on hull {hull.id}",
                )
            if mount.weapon.weapon_type not in slot.allowed_types:
                raise LoadoutError(
                    f"{mount.weapon.weapon_type.value} not allowed in "
                    f"slot {slot.name} ({hull.id})",
                )
            if _SIZE_ORDER[mount.weapon.size] > _SIZE_ORDER[slot.size]:
                raise LoadoutError(
                    f"weapon {mount.weapon.id} too large for slot {slot.name}",
                )

    def total_cost(self) -> int:
        return sum(m.weapon.cost for m in self.weapons)
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_loadout.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint + type-check + commit**

```bash
ruff check src/spacefleet/models/loadout.py tests/test_loadout.py
mypy --strict src/spacefleet/models/loadout.py
git add src/spacefleet/models/loadout.py tests/test_loadout.py
git commit -m "feat(models): add Loadout with slot validation"
```

---

## Task 2: Upgrade registry

**Files:**
- Create: `src/spacefleet/data/upgrade_registry.py`
- Create: `tests/test_upgrade_registry.py`

- [ ] **Step 1: Write failing test**

`tests/test_upgrade_registry.py`:
```python
"""Tests for UpgradeRegistry."""
from __future__ import annotations

from spacefleet.data.upgrade_registry import UpgradeProfile, UpgradeRegistry


def test_loads_default_upgrade():
    UpgradeRegistry.reset()
    up = UpgradeRegistry.get("additional_void_shield")
    assert isinstance(up, UpgradeProfile)
    assert up.cost > 0
    assert up.category == "defensive"
    assert up.effect.get("shields") == 1


def test_all_returns_dict():
    UpgradeRegistry.reset()
    catalog = UpgradeRegistry.all()
    assert "additional_void_shield" in catalog
    assert "fire_suppression_system" in catalog


def test_get_or_none_for_missing():
    UpgradeRegistry.reset()
    assert UpgradeRegistry.get_or_none("nonexistent_xyz") is None
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_upgrade_registry.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `data/upgrade_registry.py`**

```python
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_upgrade_registry.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/spacefleet/data/upgrade_registry.py tests/test_upgrade_registry.py
mypy --strict src/spacefleet/data/upgrade_registry.py
git add src/spacefleet/data/upgrade_registry.py tests/test_upgrade_registry.py
git commit -m "feat(data): add upgrade registry"
```

---

# Sprint 2 Gap Fill

## Task 3: Fleet container

**Files:**
- Create: `src/spacefleet/models/fleet.py`
- Create: `tests/test_fleet.py`

- [ ] **Step 1: Write failing test**

`tests/test_fleet.py`:
```python
"""Tests for Fleet container."""
from __future__ import annotations

from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.fleet import Fleet
from spacefleet.models.ship import Ship


def _ship(name: str) -> Ship:
    return Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_add_and_iterate():
    f = Fleet(commander_name="Lord Solar")
    f.add(_ship("a"))
    f.add(_ship("b"))
    assert len(f) == 2
    assert [s.name for s in f] == ["a", "b"]


def test_alive_filters_destroyed():
    f = Fleet()
    a = _ship("a")
    b = _ship("b")
    b.is_destroyed = True
    f.add(a)
    f.add(b)
    assert f.alive() == [a]


def test_total_hull_points():
    f = Fleet()
    s = _ship("a")
    s.hull_current = 5
    f.add(s)
    assert f.total_hull_points() == 5


def test_faction_homogeneous():
    f = Fleet()
    f.add(_ship("a"))
    assert f.faction == Faction.IMPERIAL_NAVY
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_fleet.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `models/fleet.py`**

```python
"""Fleet container — a collection of Ships under one commander."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.core.types import Faction
    from spacefleet.models.ship import Ship


@dataclass
class Fleet:
    """A homogeneous-faction fleet of ships."""

    commander_name: str = ""
    ships: list[Ship] = field(default_factory=list)

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

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_fleet.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/models/fleet.py tests/test_fleet.py
mypy --strict src/spacefleet/models/fleet.py
git add src/spacefleet/models/fleet.py tests/test_fleet.py
git commit -m "feat(models): add Fleet container"
```

---

## Task 4: Morale module (pure helpers)

**Files:**
- Create: `src/spacefleet/models/morale.py`
- Create: `tests/test_morale.py`

- [ ] **Step 1: Write failing test**

`tests/test_morale.py`:
```python
"""Tests for the morale helpers."""
from __future__ import annotations

from spacefleet.core.types import MoraleState
from spacefleet.models.morale import (
    accuracy_factor,
    morale_state,
    speed_cap,
)


def test_state_buckets():
    assert morale_state(100) == MoraleState.FULL
    assert morale_state(75) == MoraleState.FULL
    assert morale_state(74) == MoraleState.SHAKEN
    assert morale_state(50) == MoraleState.SHAKEN
    assert morale_state(49) == MoraleState.WAVERING
    assert morale_state(25) == MoraleState.WAVERING
    assert morale_state(24) == MoraleState.BREAKING
    assert morale_state(1) == MoraleState.BREAKING
    assert morale_state(0) == MoraleState.MUTINY


def test_accuracy_factor_drops_with_morale():
    assert accuracy_factor(MoraleState.FULL) == 1.0
    assert accuracy_factor(MoraleState.SHAKEN) == 0.9
    assert accuracy_factor(MoraleState.WAVERING) == 0.75
    assert accuracy_factor(MoraleState.BREAKING) == 0.5
    assert accuracy_factor(MoraleState.MUTINY) == 0.0


def test_speed_cap_brackets():
    assert speed_cap(MoraleState.FULL, 20.0) == 20.0
    assert speed_cap(MoraleState.SHAKEN, 20.0) == 20.0
    assert speed_cap(MoraleState.WAVERING, 20.0) == 15.0
    assert speed_cap(MoraleState.BREAKING, 20.0) == 10.0
    assert speed_cap(MoraleState.MUTINY, 20.0) == 0.0
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_morale.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `models/morale.py`**

```python
"""Pure helpers for morale brackets, accuracy factor and speed caps.

The Ship class delegates state-bracket lookups to these helpers so
combat code can call them without holding a Ship reference.
"""
from __future__ import annotations

from spacefleet.core.types import MoraleState


def morale_state(morale: int) -> MoraleState:
    """Return the bracket for a morale value in [0, 100]."""
    if morale >= 75:
        return MoraleState.FULL
    if morale >= 50:
        return MoraleState.SHAKEN
    if morale >= 25:
        return MoraleState.WAVERING
    if morale >= 1:
        return MoraleState.BREAKING
    return MoraleState.MUTINY


_ACCURACY: dict[MoraleState, float] = {
    MoraleState.FULL: 1.0,
    MoraleState.SHAKEN: 0.9,
    MoraleState.WAVERING: 0.75,
    MoraleState.BREAKING: 0.5,
    MoraleState.MUTINY: 0.0,
}


def accuracy_factor(state: MoraleState) -> float:
    """Hit-count multiplier for ships at this morale bracket."""
    return _ACCURACY[state]


def speed_cap(state: MoraleState, max_speed: float) -> float:
    """Maximum speed permitted at this morale bracket.

    * FULL/SHAKEN: no penalty
    * WAVERING: ``max - 5`` GU
    * BREAKING: half speed
    * MUTINY: 0
    """
    if state in (MoraleState.FULL, MoraleState.SHAKEN):
        return max_speed
    if state == MoraleState.WAVERING:
        return max(0.0, max_speed - 5.0)
    if state == MoraleState.BREAKING:
        return max_speed * 0.5
    return 0.0
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_morale.py -v`
Expected: 3 passed.

- [ ] **Step 5: Wire Ship to delegate**

Edit `src/spacefleet/models/ship.py` — replace the body of `morale_state` to call the new helper:

```python
    def morale_state(self) -> MoraleState:
        from spacefleet.models.morale import morale_state as _ms
        return _ms(self.morale)
```

- [ ] **Step 6: Run full suite**

Run: `pytest -q`
Expected: full suite green.

- [ ] **Step 7: Commit**

```bash
ruff check src/spacefleet/models/morale.py tests/test_morale.py src/spacefleet/models/ship.py
mypy --strict src/spacefleet/models/morale.py src/spacefleet/models/ship.py
git add src/spacefleet/models/morale.py src/spacefleet/models/ship.py tests/test_morale.py
git commit -m "refactor(models): extract morale helpers into models/morale.py"
```

---

## Task 5: Subsystems module

**Files:**
- Create: `src/spacefleet/models/subsystems.py`
- Create: `tests/test_subsystems.py`

- [ ] **Step 1: Write failing test**

`tests/test_subsystems.py`:
```python
"""Tests for the Subsystems dataclass."""
from __future__ import annotations

from spacefleet.models.subsystems import Subsystems


def test_default_all_operational():
    s = Subsystems()
    assert s.generator and s.deck and s.engines and s.weapons
    assert s.all_operational()


def test_disable_one():
    s = Subsystems()
    s.engines = False
    assert not s.all_operational()
    assert s.damaged_list() == ["engines"]


def test_repair_all():
    s = Subsystems(generator=False, deck=False)
    s.repair_all()
    assert s.all_operational()
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_subsystems.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `models/subsystems.py`**

```python
"""Four-subsystem health tracker shared by ships and serializers."""
from __future__ import annotations

from dataclasses import dataclass

SUBSYSTEM_NAMES = ("generator", "deck", "engines", "weapons")


@dataclass
class Subsystems:
    """Operational state for the four critical ship subsystems."""

    generator: bool = True
    deck: bool = True
    engines: bool = True
    weapons: bool = True

    def all_operational(self) -> bool:
        return self.generator and self.deck and self.engines and self.weapons

    def damaged_list(self) -> list[str]:
        return [
            name
            for name in SUBSYSTEM_NAMES
            if not getattr(self, name)
        ]

    def repair_all(self) -> None:
        self.generator = True
        self.deck = True
        self.engines = True
        self.weapons = True
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_subsystems.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/models/subsystems.py tests/test_subsystems.py
mypy --strict src/spacefleet/models/subsystems.py
git add src/spacefleet/models/subsystems.py tests/test_subsystems.py
git commit -m "feat(models): add Subsystems dataclass"
```

---

## Task 6: Stance module (cooldown helpers)

**Files:**
- Create: `src/spacefleet/models/stance.py`
- Create: `tests/test_stance_module.py`

- [ ] **Step 1: Write failing test**

`tests/test_stance_module.py`:
```python
"""Tests for the stance state helpers."""
from __future__ import annotations

from spacefleet.core.types import Stance
from spacefleet.models.stance import StanceState, can_switch


def test_can_switch_when_no_cooldown():
    state = StanceState(stance=Stance.STANDARD)
    assert can_switch(state, deck_operational=True, morale=100) is True


def test_cannot_switch_with_cooldown():
    state = StanceState(stance=Stance.LOCK_ON, cooldown_remaining=1)
    assert can_switch(state, deck_operational=True, morale=100) is False


def test_cannot_switch_without_deck():
    state = StanceState(stance=Stance.STANDARD)
    assert can_switch(state, deck_operational=False, morale=100) is False


def test_cannot_switch_in_mutiny():
    state = StanceState(stance=Stance.STANDARD)
    assert can_switch(state, deck_operational=True, morale=0) is False


def test_tick_decrements_cooldown():
    state = StanceState(stance=Stance.LOCK_ON, cooldown_remaining=2)
    state.tick()
    assert state.cooldown_remaining == 1
    state.tick()
    state.tick()
    assert state.cooldown_remaining == 0
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_stance_module.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `models/stance.py`**

```python
"""Stance state container + pure switch-eligibility helpers."""
from __future__ import annotations

from dataclasses import dataclass

from spacefleet.core.types import Stance


@dataclass
class StanceState:
    """Mutable stance + cooldown carried by a ship."""

    stance: Stance = Stance.STANDARD
    cooldown_remaining: int = 0

    def tick(self) -> None:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1


def can_switch(
    state: StanceState,
    *,
    deck_operational: bool,
    morale: int,
) -> bool:
    """True when the ship is allowed to switch stance this turn."""
    if state.cooldown_remaining > 0:
        return False
    if not deck_operational:
        return False
    return morale > 0
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_stance_module.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/models/stance.py tests/test_stance_module.py
mypy --strict src/spacefleet/models/stance.py
git add src/spacefleet/models/stance.py tests/test_stance_module.py
git commit -m "feat(models): add StanceState helpers"
```

---

## Task 7: Spatial movement + combustion spending

**Files:**
- Create: `src/spacefleet/spatial/movement.py`
- Create: `tests/test_movement.py`

The current `Ship.set_speed` simply clamps; the roadmap promises a *combustion gauge* that is **spent** when accelerating. This task adds that.

- [ ] **Step 1: Write failing test**

`tests/test_movement.py`:
```python
"""Tests for spatial.movement (combustion gauge)."""
from __future__ import annotations

import pytest

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.spatial.movement import (
    CombustionError,
    accelerate,
    combustion_cost,
    decelerate,
)


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_cost_is_speed_delta():
    assert combustion_cost(0.0, 10.0) == 10
    assert combustion_cost(10.0, 25.0) == 15
    assert combustion_cost(20.0, 5.0) == 0  # decel free


def test_accelerate_spends_combustion():
    ship = _ship()
    ship.combustion = 50
    accelerate(ship, target_speed=10.0)
    assert ship.speed == 10.0
    assert ship.combustion == 40


def test_accelerate_clamps_to_max_speed():
    ship = _ship()
    ship.combustion = 999
    accelerate(ship, target_speed=999.0)
    assert ship.speed == ship.effective_speed_max


def test_accelerate_insufficient_combustion_raises():
    ship = _ship()
    ship.combustion = 5
    with pytest.raises(CombustionError):
        accelerate(ship, target_speed=20.0)


def test_decelerate_is_free():
    ship = _ship()
    ship.combustion = 10
    ship.speed = 20.0
    decelerate(ship, target_speed=5.0)
    assert ship.speed == 5.0
    assert ship.combustion == 10  # untouched
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_movement.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `spatial/movement.py`**

```python
"""Movement helpers: combustion spending + speed transitions.

The geometry primitives (``apply_drift``, ``apply_turn``) stay on
``Ship``.  This module owns the *combustion economy* — accelerating
costs combustion points; decelerating is free.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


class CombustionError(RuntimeError):
    """Raised when a ship cannot pay the combustion cost of a manoeuvre."""


def combustion_cost(current_speed: float, target_speed: float) -> int:
    """Combustion points required to change *current_speed* to *target_speed*.

    Acceleration: ``ceil(target − current)``.  Deceleration: free.
    """
    delta = target_speed - current_speed
    if delta <= 0:
        return 0
    return int(delta + 0.999999)  # ceil for non-integer speeds


def accelerate(ship: Ship, *, target_speed: float) -> None:
    """Spend combustion to raise *ship*'s speed.

    Clamps to ``effective_speed_max``.  Raises :class:`CombustionError`
    if the ship lacks the combustion to reach the (clamped) target.
    """
    target = min(target_speed, ship.effective_speed_max)
    cost = combustion_cost(ship.speed, target)
    if cost > ship.combustion:
        raise CombustionError(
            f"{ship.name}: needs {cost} combustion, has {ship.combustion}",
        )
    ship.combustion -= cost
    ship.speed = target


def decelerate(ship: Ship, *, target_speed: float) -> None:
    """Reduce *ship*'s speed for free.  Clamps to ``[0, current]``."""
    target = max(0.0, min(target_speed, ship.speed))
    ship.speed = target
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_movement.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/spatial/movement.py tests/test_movement.py
mypy --strict src/spacefleet/spatial/movement.py
git add src/spacefleet/spatial/movement.py tests/test_movement.py
git commit -m "feat(spatial): add combustion-aware movement helpers"
```

---

## Task 8: Movement phase resolver

**Files:**
- Create: `src/spacefleet/phases/movement_phase.py`
- Create: `tests/test_movement_phase.py`

- [ ] **Step 1: Write failing test**

`tests/test_movement_phase.py`:
```python
"""Tests for the movement phase resolver."""
from __future__ import annotations

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.phases.movement_phase import MoveOrder, resolve_movement_phase


def _ship(name: str, *, x: float = 0.0, y: float = 0.0) -> Ship:
    return Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(x, y),
        heading=0.0,
    )


def test_no_orders_drifts_ships():
    ship = _ship("a")
    ship.speed = 10.0
    log = resolve_movement_phase([ship], orders={})
    assert ship.position.y > 0  # drifted forward
    assert any(e.kind == "drift" for e in log)


def test_accelerate_then_drift():
    ship = _ship("a")
    ship.combustion = 50
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(target_speed=10.0)},
    )
    assert ship.speed == 10.0
    assert ship.combustion == 40
    assert any(e.kind == "speed" for e in log)
    assert any(e.kind == "drift" for e in log)


def test_turn_order_pivots():
    ship = _ship("a")
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(turn_degrees=30.0)},
    )
    assert any(e.kind == "turn" for e in log)
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_movement_phase.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `phases/movement_phase.py`**

```python
"""Movement phase resolver.

Applies speed/turn orders, then drifts every alive ship a half turn.
Returns a list of typed events the renderer can format.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.spatial.movement import CombustionError, accelerate, decelerate

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class MoveOrder:
    """One ship's movement intent for the phase."""

    target_speed: float | None = None
    turn_degrees: float | None = None


@dataclass
class MoveEvent:
    """Outcome event produced by the phase resolver."""

    kind: str  # "speed" | "turn" | "drift" | "blocked"
    ship_id: str
    detail: str = ""


def resolve_movement_phase(
    ships: list[Ship],
    orders: dict[str, MoveOrder],
    *,
    drift_fraction: float = 1.0,
) -> list[MoveEvent]:
    """Apply orders + drift, returning the events that occurred."""
    events: list[MoveEvent] = []

    for ship in ships:
        if not ship.alive:
            continue
        order = orders.get(ship.id)
        if order is None:
            continue

        if order.target_speed is not None:
            try:
                if order.target_speed >= ship.speed:
                    accelerate(ship, target_speed=order.target_speed)
                else:
                    decelerate(ship, target_speed=order.target_speed)
                events.append(
                    MoveEvent(
                        kind="speed",
                        ship_id=ship.id,
                        detail=f"speed → {ship.speed:.0f}",
                    ),
                )
            except CombustionError as exc:
                events.append(
                    MoveEvent(kind="blocked", ship_id=ship.id, detail=str(exc)),
                )

        if order.turn_degrees is not None and order.turn_degrees != 0.0:
            ship.apply_turn(order.turn_degrees)
            events.append(
                MoveEvent(
                    kind="turn",
                    ship_id=ship.id,
                    detail=f"{order.turn_degrees:+.0f}°",
                ),
            )

    for ship in ships:
        if not ship.alive:
            continue
        before, after = ship.apply_drift(drift_fraction)
        events.append(
            MoveEvent(
                kind="drift",
                ship_id=ship.id,
                detail=f"hdg {before:.0f}→{after:.0f}",
            ),
        )

    return events
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_movement_phase.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/phases/movement_phase.py tests/test_movement_phase.py
mypy --strict src/spacefleet/phases/movement_phase.py
git add src/spacefleet/phases/movement_phase.py tests/test_movement_phase.py
git commit -m "feat(phases): add movement phase resolver"
```

---

# Sprint 3 Gap Fill

## Task 9: combat/gunnery.py — extract gunnery table

**Files:**
- Create: `src/spacefleet/combat/gunnery.py`
- Create: `tests/test_gunnery.py`
- Modify: `src/spacefleet/combat/resolution.py` — re-export

- [ ] **Step 1: Write failing test**

`tests/test_gunnery.py`:
```python
"""Tests for combat.gunnery — gunnery table lookup + battery resolver."""
from __future__ import annotations

from spacefleet.combat.gunnery import (
    GUNNERY_COLUMNS,
    GUNNERY_TABLE,
    column_index,
    lookup_hits,
    target_aspect,
)
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship(*, x: float, y: float, heading: float) -> Ship:
    return Ship.from_profile(
        ship_id=f"s_{x}_{y}",
        name="S",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(x, y),
        heading=heading,
    )


def test_table_has_16_rows():
    assert len(GUNNERY_TABLE) == 16
    assert GUNNERY_COLUMNS == [
        "far_closing", "closing", "abeam", "running", "far_running",
    ]


def test_lookup_clamps_strength():
    assert lookup_hits(strength=1, column=2) == 1  # 1@abeam = 1
    assert lookup_hits(strength=99, column=4) == 9  # clamped to 16


def test_column_index_centred_at_2():
    assert column_index(aspect_shift=0, stance_shift=0) == 2
    assert column_index(aspect_shift=-1, stance_shift=0) == 1
    assert column_index(aspect_shift=1, stance_shift=1) == 4
    assert column_index(aspect_shift=-1, stance_shift=-1) == 0
    # Clamped at 0 / 4
    assert column_index(aspect_shift=-2, stance_shift=-2) == 0
    assert column_index(aspect_shift=2, stance_shift=2) == 4


def test_target_aspect_closing_when_prow_to_attacker():
    target = _ship(x=0, y=0, heading=180.0)  # facing -y
    attacker = _ship(x=0, y=-30, heading=0.0)  # below, but target faces it
    name, shift = target_aspect(attacker, target)
    assert name == "closing"
    assert shift == -1
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_gunnery.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `combat/gunnery.py`**

```python
"""Battery gunnery table + helper lookups.

This module owns the gunnery table and target-aspect calculation.
The full ``resolve_battery_attack`` resolver still lives in
``combat.resolution`` for now; this is the canonical home for the
table itself.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.spatial.geometry import bearing_from_to, relative_bearing

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


GUNNERY_COLUMNS = ["far_closing", "closing", "abeam", "running", "far_running"]


GUNNERY_TABLE: dict[int, list[int]] = {
    1:  [0, 0, 1, 1, 1],
    2:  [0, 1, 1, 1, 2],
    3:  [0, 1, 1, 2, 2],
    4:  [1, 1, 2, 2, 3],
    5:  [1, 1, 2, 3, 3],
    6:  [1, 2, 2, 3, 4],
    7:  [1, 2, 3, 3, 4],
    8:  [1, 2, 3, 4, 5],
    9:  [2, 2, 3, 4, 5],
    10: [2, 3, 4, 4, 6],
    11: [2, 3, 4, 5, 6],
    12: [2, 3, 4, 5, 7],
    13: [3, 3, 5, 6, 7],
    14: [3, 4, 5, 6, 8],
    15: [3, 4, 5, 7, 8],
    16: [3, 4, 6, 7, 9],
}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def column_index(*, aspect_shift: int, stance_shift: int) -> int:
    """Final column index in [0, 4] given the aspect + stance shifts."""
    return _clamp(2 + aspect_shift + stance_shift, 0, 4)


def lookup_hits(*, strength: int, column: int) -> int:
    """Look up hit count, clamping strength to the table range."""
    s = _clamp(strength, 1, max(GUNNERY_TABLE.keys()))
    c = _clamp(column, 0, 4)
    return GUNNERY_TABLE[s][c]


def target_aspect(attacker: Ship, target: Ship) -> tuple[str, int]:
    """Return ``(aspect_name, shift)`` for the face the target presents.

    Shift values:
        ``-1`` closing (target shows prow), ``0`` abeam, ``+1`` running.
    """
    abs_bearing = bearing_from_to(target.position, attacker.position)
    rel = relative_bearing(target.heading, abs_bearing)
    abs_rel = abs(rel)
    if abs_rel <= 45:
        return "closing", -1
    if abs_rel <= 135:
        return "abeam", 0
    return "running", 1
```

- [ ] **Step 4: Wire `combat/resolution.py` to import from `gunnery`**

In `src/spacefleet/combat/resolution.py`, replace the inline table + `_get_target_aspect` with imports:

```python
# top of file, with other imports
from spacefleet.combat.gunnery import (
    GUNNERY_COLUMNS,
    GUNNERY_TABLE,
    column_index,
    lookup_hits,
    target_aspect as _get_target_aspect,
)
```

Delete the local `GUNNERY_COLUMNS`, `GUNNERY_TABLE`, and `_get_target_aspect` definitions. Replace the column/lookup arithmetic in `resolve_battery_attack` with calls to `column_index` and `lookup_hits`:

```python
    aspect_name, aspect_shift = _get_target_aspect(attacker, target)
    result.target_aspect = aspect_name

    col_idx = column_index(
        aspect_shift=aspect_shift,
        stance_shift=attacker_stance.gunnery_column_shift,
    )
    result.gunnery_column = GUNNERY_COLUMNS[col_idx]

    raw_hits = lookup_hits(strength=fp, column=col_idx)
    raw_hits = max(0, int(raw_hits * _morale_accuracy_factor(attacker)))
    result.raw_hits = raw_hits
```

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: full suite green (existing combat tests still pass, new gunnery tests pass).

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/spacefleet/combat/gunnery.py src/spacefleet/combat/resolution.py tests/test_gunnery.py
mypy --strict src/spacefleet/combat/gunnery.py src/spacefleet/combat/resolution.py
git add src/spacefleet/combat/gunnery.py src/spacefleet/combat/resolution.py tests/test_gunnery.py
git commit -m "refactor(combat): split gunnery table into combat/gunnery.py"
```

---

## Task 10: combat/lance.py — extract lance resolver

**Files:**
- Create: `src/spacefleet/combat/lance.py`
- Create: `tests/test_lance.py`
- Modify: `src/spacefleet/combat/resolution.py` — re-export

- [ ] **Step 1: Write failing test**

`tests/test_lance.py`:
```python
"""Tests for combat.lance."""
from __future__ import annotations

from spacefleet.combat.lance import lance_hit_count
from spacefleet.dice import DiceRoller


def test_count_hits_4plus():
    assert lance_hit_count([1, 3, 4, 6]) == 2
    assert lance_hit_count([5, 5, 5]) == 3
    assert lance_hit_count([1, 2, 3]) == 0


def test_lance_resolver_uses_4plus(monkeypatch):
    # Sanity: a deterministic dice roller produces a stable count
    dr = DiceRoller(seed=1)
    rolls = dr.roll_d6(8)
    assert lance_hit_count(rolls) >= 0
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_lance.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `combat/lance.py`**

```python
"""Lance resolution helpers — 1D6 per strength, 4+ hits, ignores armor."""
from __future__ import annotations

from collections.abc import Iterable

LANCE_HIT_THRESHOLD = 4


def lance_hit_count(rolls: Iterable[int]) -> int:
    """Number of dice in *rolls* that meet the lance hit threshold."""
    return sum(1 for r in rolls if r >= LANCE_HIT_THRESHOLD)
```

- [ ] **Step 4: Wire `combat/resolution.py`**

In `resolve_lance_attack`, replace `raw_hits = sum(1 for r in rolls if r >= 4)` with `raw_hits = lance_hit_count(rolls)`. Add the import at the top:

```python
from spacefleet.combat.lance import lance_hit_count
```

- [ ] **Step 5: Run suite**

Run: `pytest -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
ruff check src/spacefleet/combat/lance.py src/spacefleet/combat/resolution.py tests/test_lance.py
mypy --strict src/spacefleet/combat/lance.py
git add src/spacefleet/combat/lance.py src/spacefleet/combat/resolution.py tests/test_lance.py
git commit -m "refactor(combat): split lance hit counting into combat/lance.py"
```

---

## Task 11: combat/damage.py — extract damage pipeline

**Files:**
- Create: `src/spacefleet/combat/damage.py`
- Create: `tests/test_damage.py`
- Modify: `src/spacefleet/combat/resolution.py` — call helper

- [ ] **Step 1: Write failing test**

`tests/test_damage.py`:
```python
"""Tests for combat.damage — shield → armor → hull pipeline."""
from __future__ import annotations

from spacefleet.combat.damage import DamageReport, apply_damage_pipeline
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="t",
        name="T",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 30.0),
        heading=180.0,
    )


def test_shields_absorb_first():
    ship = _ship()
    ship.shields_current = 3
    dr = DiceRoller(seed=1)
    report = apply_damage_pipeline(
        target=ship,
        hits=2,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=dr,
    )
    assert report.shield_blocked == 2
    assert ship.shields_current == 1


def test_overflow_rolls_armor():
    ship = _ship()
    ship.shields_current = 0
    dr = DiceRoller(seed=42)
    report = apply_damage_pipeline(
        target=ship,
        hits=3,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=dr,
    )
    assert isinstance(report, DamageReport)
    assert report.shield_blocked == 0
    assert report.penetrating + report.armor_saves == 3


def test_zero_hits_short_circuits():
    ship = _ship()
    dr = DiceRoller(seed=1)
    report = apply_damage_pipeline(
        target=ship,
        hits=0,
        relative_bearing=0.0,
        damage_per_hit=1,
        dice_roller=dr,
    )
    assert report.hull_damage == 0
    assert report.penetrating == 0
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_damage.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `combat/damage.py`**

```python
"""Shield → armor → hull damage pipeline.

Pure helper extracted from ``combat/resolution.py``.  Operates on the
target ship in place and returns a structured report.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class DamageReport:
    """Aggregate counts produced by one damage application."""

    shield_blocked: int = 0
    armor_saves: int = 0
    penetrating: int = 0
    hull_damage: int = 0


def apply_damage_pipeline(
    *,
    target: Ship,
    hits: int,
    relative_bearing: float,
    damage_per_hit: int,
    ignores_armor: bool = False,
    dice_roller: DiceRoller | None = None,
) -> DamageReport:
    """Drive the shield → armor → hull chain for *hits* potential hits.

    Returns a :class:`DamageReport` and mutates *target* (shield + hull).
    Morale changes are applied separately by the caller.
    """
    dr = dice_roller or default_dice
    report = DamageReport()
    if hits <= 0:
        return report

    after_shields = target.absorb_shields(hits)
    report.shield_blocked = hits - after_shields

    if after_shields == 0:
        return report

    if ignores_armor:
        report.penetrating = after_shields
        report.hull_damage = after_shields * damage_per_hit
        if report.hull_damage > 0:
            target.take_hull_damage(report.hull_damage)
        return report

    armor = target.armor_for_bearing(relative_bearing)
    for _ in range(after_shields):
        roll = dr.d6()
        if roll >= armor:
            report.penetrating += 1
            report.hull_damage += damage_per_hit
        else:
            report.armor_saves += 1

    if report.hull_damage > 0:
        target.take_hull_damage(report.hull_damage)

    return report
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_damage.py -v`
Expected: 3 passed.

- [ ] **Step 5: (Optional) Use helper from `combat/resolution.py`**

This step is OPTIONAL — adopt only if the existing `resolve_battery_attack` tests still pass after the swap. The complication is that the existing resolver also computes `HitDetail` per shot for display; the helper above produces aggregates only. If preserving `HitDetail` matters, leave `resolve_battery_attack` untouched and keep `combat/damage.py` as the public API for new callers (sprint 4 phase resolvers). If `HitDetail` can be derived from aggregates, route `resolve_battery_attack` through `apply_damage_pipeline` and rebuild `HitDetail` from the report. Run `pytest tests/test_stances.py tests/test_sprint3.py -v` and only commit the swap if both stay green.

- [ ] **Step 6: Commit**

```bash
ruff check src/spacefleet/combat/damage.py tests/test_damage.py
mypy --strict src/spacefleet/combat/damage.py
git add src/spacefleet/combat/damage.py tests/test_damage.py
git commit -m "feat(combat): add damage pipeline helper"
```

---

## Task 12: combat/morale_effects.py

**Files:**
- Create: `src/spacefleet/combat/morale_effects.py`
- Create: `tests/test_morale_effects.py`

- [ ] **Step 1: Write failing test**

`tests/test_morale_effects.py`:
```python
"""Tests for combat.morale_effects."""
from __future__ import annotations

from spacefleet.combat.morale_effects import (
    MORALE_PER_BOARDING_CREW_HIT,
    MORALE_PER_CRIT,
    MORALE_PER_HULL_DAMAGE,
    apply_boarding_crew_morale,
    apply_critical_hit_morale,
    apply_hull_damage_morale,
)
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="t",
        name="T",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_hull_damage_morale():
    ship = _ship()
    apply_hull_damage_morale(ship, hull_damage=2)
    assert ship.morale == 100 + MORALE_PER_HULL_DAMAGE * 2


def test_critical_hit_morale():
    ship = _ship()
    apply_critical_hit_morale(ship)
    assert ship.morale == 100 + MORALE_PER_CRIT


def test_boarding_crew_morale():
    ship = _ship()
    apply_boarding_crew_morale(ship, crew_damage_count=3)
    assert ship.morale == 100 + MORALE_PER_BOARDING_CREW_HIT * 3
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_morale_effects.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `combat/morale_effects.py`**

```python
"""Centralised morale change triggers.

Combat resolvers and boarding code call into this module so the
constants live in one place and can be tweaked for balance.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


MORALE_PER_HULL_DAMAGE = -3
MORALE_PER_CRIT = -5
MORALE_PER_BOARDING_CREW_HIT = -10


def apply_hull_damage_morale(ship: Ship, *, hull_damage: int) -> int:
    """Drop morale proportional to hull damage taken.  Returns delta."""
    if hull_damage <= 0:
        return 0
    return ship.apply_morale_change(MORALE_PER_HULL_DAMAGE * hull_damage)


def apply_critical_hit_morale(ship: Ship) -> int:
    """Flat morale loss for any critical hit landed."""
    return ship.apply_morale_change(MORALE_PER_CRIT)


def apply_boarding_crew_morale(ship: Ship, *, crew_damage_count: int) -> int:
    """Morale loss for each successful boarding crew-damage roll."""
    if crew_damage_count <= 0:
        return 0
    return ship.apply_morale_change(
        MORALE_PER_BOARDING_CREW_HIT * crew_damage_count,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_morale_effects.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/combat/morale_effects.py tests/test_morale_effects.py
mypy --strict src/spacefleet/combat/morale_effects.py
git add src/spacefleet/combat/morale_effects.py tests/test_morale_effects.py
git commit -m "feat(combat): centralise morale change triggers"
```

---

## Task 13: phases/shooting_phase.py

**Files:**
- Create: `src/spacefleet/phases/shooting_phase.py`
- Create: `tests/test_shooting_phase.py`

This is a thin orchestrator on top of `combat/resolution.py` so the spec's phase split exists.

- [ ] **Step 1: Write failing test**

`tests/test_shooting_phase.py`:
```python
"""Tests for the shooting phase resolver."""
from __future__ import annotations

from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.phases.shooting_phase import FireOrder, resolve_shooting_phase


def _ship(name: str, *, x: float, faction: Faction) -> Ship:
    s = Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(x, 0.0),
        heading=90.0 if x < 0 else 270.0,
    )
    s.faction = faction
    return s


def test_no_orders_returns_empty():
    a = _ship("a", x=-30, faction=Faction.IMPERIAL_NAVY)
    b = _ship("b", x=30, faction=Faction.CHAOS_FLEET)
    results = resolve_shooting_phase(
        ships=[a, b], orders={}, dice_roller=DiceRoller(seed=1),
    )
    assert results == []


def test_fire_order_produces_attack_result():
    a = _ship("a", x=-30, faction=Faction.IMPERIAL_NAVY)
    b = _ship("b", x=30, faction=Faction.CHAOS_FLEET)
    weapon = a.weapons[1]  # Starboard battery (faces +x)
    results = resolve_shooting_phase(
        ships=[a, b],
        orders={"a": [FireOrder(slot_id=weapon.slot_id, target_id="b")]},
        dice_roller=DiceRoller(seed=1),
    )
    assert len(results) == 1
    assert results[0].attacker_name == "a"
    assert results[0].target_name == "b"
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_shooting_phase.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `phases/shooting_phase.py`**

```python
"""Shooting phase orchestrator.

Iterates fire orders, dispatches each through ``combat.resolution``,
and returns the full list of :class:`AttackResult` records for the
renderer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.combat.resolution import AttackResult, resolve_attack
from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class FireOrder:
    """One weapon firing order."""

    slot_id: int
    target_id: str


def resolve_shooting_phase(
    *,
    ships: list[Ship],
    orders: dict[str, list[FireOrder]],
    dice_roller: DiceRoller | None = None,
) -> list[AttackResult]:
    """Resolve every fire order in deterministic order.

    Returns the list of :class:`AttackResult` records (skipping orders
    referencing a dead attacker or missing target).
    """
    dr = dice_roller or default_dice
    by_id = {s.id: s for s in ships}
    results: list[AttackResult] = []

    for ship_id in sorted(orders):
        ship = by_id.get(ship_id)
        if ship is None or not ship.alive:
            continue
        for order in orders[ship_id]:
            target = by_id.get(order.target_id)
            if target is None or not target.alive:
                continue
            weapon = next(
                (w for w in ship.weapons if w.slot_id == order.slot_id),
                None,
            )
            if weapon is None:
                continue
            results.append(
                resolve_attack(ship, weapon, target, dice_roller=dr),
            )

    return results
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_shooting_phase.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/phases/shooting_phase.py tests/test_shooting_phase.py
mypy --strict src/spacefleet/phases/shooting_phase.py
git add src/spacefleet/phases/shooting_phase.py tests/test_shooting_phase.py
git commit -m "feat(phases): add shooting phase resolver"
```

---

# Sprint 4 Gap Fill

## Task 14: core/game_state.py

**Files:**
- Create: `src/spacefleet/core/game_state.py`
- Create: `tests/test_core_game_state.py`

The existing `net/game_state.py` is server-specific. Sprint 4 calls for a *core* game state that the CLI can use without pulling in network code.

- [ ] **Step 1: Write failing test**

`tests/test_core_game_state.py`:
```python
"""Tests for core.game_state."""
from __future__ import annotations

from spacefleet.core.game_state import CoreGameState
from spacefleet.core.types import Faction, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship(name: str, faction: Faction) -> Ship:
    s = Ship.from_profile(
        ship_id=name,
        name=name,
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )
    s.faction = faction
    return s


def test_add_ship_and_lookup():
    state = CoreGameState()
    a = _ship("a", Faction.IMPERIAL_NAVY)
    state.add_ship(a)
    assert state.get_ship("a") is a
    assert state.alive_ships() == [a]


def test_enemy_lookup():
    state = CoreGameState()
    a = _ship("a", Faction.IMPERIAL_NAVY)
    b = _ship("b", Faction.CHAOS_FLEET)
    state.add_ship(a)
    state.add_ship(b)
    assert state.enemies_of(a) == [b]
    assert state.friendlies_of(a) == []


def test_advance_turn_increments():
    state = CoreGameState()
    assert state.turn == 0
    state.advance_turn()
    assert state.turn == 1


def test_game_over_when_one_faction_left():
    state = CoreGameState()
    a = _ship("a", Faction.IMPERIAL_NAVY)
    b = _ship("b", Faction.CHAOS_FLEET)
    state.add_ship(a)
    state.add_ship(b)
    assert not state.is_game_over()
    b.is_destroyed = True
    assert state.is_game_over()
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_core_game_state.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `core/game_state.py`**

```python
"""Core (network-free) game state.

Holds the ship roster, current turn, and lookup helpers.  The
``net.game_state.GameState`` server class composes/extends this for
multiplayer-specific bookkeeping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.dice import DiceRoller

if TYPE_CHECKING:
    from spacefleet.core.types import Faction
    from spacefleet.models.ship import Ship


@dataclass
class CoreGameState:
    """Battle-only state shared by CLI, AI and server layers."""

    turn: int = 0
    ships: dict[str, Ship] = field(default_factory=dict)
    dice: DiceRoller = field(default_factory=DiceRoller)

    def add_ship(self, ship: Ship) -> None:
        self.ships[ship.id] = ship

    def remove_ship(self, ship_id: str) -> None:
        self.ships.pop(ship_id, None)

    def get_ship(self, ship_id: str) -> Ship:
        return self.ships[ship_id]

    def alive_ships(self) -> list[Ship]:
        return [s for s in self.ships.values() if s.alive]

    def enemies_of(self, ship: Ship) -> list[Ship]:
        return [
            s for s in self.ships.values()
            if s.alive and s.faction != ship.faction
        ]

    def friendlies_of(self, ship: Ship) -> list[Ship]:
        return [
            s for s in self.ships.values()
            if s.alive and s.faction == ship.faction and s.id != ship.id
        ]

    def advance_turn(self) -> None:
        self.turn += 1

    def is_game_over(self) -> bool:
        factions: set[Faction] = set()
        for s in self.ships.values():
            if s.alive:
                factions.add(s.faction)
        return len(factions) < 2
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_core_game_state.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
ruff check src/spacefleet/core/game_state.py tests/test_core_game_state.py
mypy --strict src/spacefleet/core/game_state.py
git add src/spacefleet/core/game_state.py tests/test_core_game_state.py
git commit -m "feat(core): add CoreGameState (network-free)"
```

---

## Task 15: core/events.py — event bus

**Files:**
- Create: `src/spacefleet/core/events.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: Write failing test**

`tests/test_events.py`:
```python
"""Tests for the core event bus."""
from __future__ import annotations

from dataclasses import dataclass

from spacefleet.core.events import Event, EventBus


@dataclass
class HitEvent(Event):
    target: str = ""
    damage: int = 0


def test_subscribe_and_publish():
    bus = EventBus()
    received: list[HitEvent] = []
    bus.subscribe(HitEvent, received.append)
    bus.publish(HitEvent(target="enemy", damage=3))
    assert received == [HitEvent(target="enemy", damage=3)]


def test_multiple_subscribers():
    bus = EventBus()
    a: list[Event] = []
    b: list[Event] = []
    bus.subscribe(HitEvent, a.append)
    bus.subscribe(HitEvent, b.append)
    bus.publish(HitEvent(target="x", damage=1))
    assert len(a) == 1
    assert len(b) == 1


def test_unrelated_events_ignored():
    @dataclass
    class OtherEvent(Event):
        pass

    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(HitEvent, seen.append)
    bus.publish(OtherEvent())
    assert seen == []


def test_unsubscribe():
    bus = EventBus()
    seen: list[Event] = []
    handler = seen.append
    bus.subscribe(HitEvent, handler)
    bus.unsubscribe(HitEvent, handler)
    bus.publish(HitEvent(target="x", damage=1))
    assert seen == []
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_events.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/events.py`**

```python
"""Lightweight typed event bus for in-game notifications.

Phases publish events; CLI/UI/AI layers subscribe.  No external deps.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

EventT = TypeVar("EventT", bound="Event")


@dataclass
class Event:
    """Base class for all in-game events."""


Handler = Callable[[EventT], None]


class EventBus:
    """Class-based pub/sub bus.

    Subscribers register a handler for a specific :class:`Event`
    subclass; ``publish`` dispatches to handlers whose registered
    type matches the event's runtime class exactly.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler[Event]]] = {}

    def subscribe(
        self,
        event_type: type[EventT],
        handler: Handler[EventT],
    ) -> None:
        bucket = self._handlers.setdefault(event_type, [])
        bucket.append(handler)  # type: ignore[arg-type]

    def unsubscribe(
        self,
        event_type: type[EventT],
        handler: Handler[EventT],
    ) -> None:
        bucket = self._handlers.get(event_type)
        if not bucket:
            return
        try:
            bucket.remove(handler)  # type: ignore[arg-type]
        except ValueError:
            pass

    def publish(self, event: Event) -> None:
        for handler in list(self._handlers.get(type(event), [])):
            handler(event)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_events.py -v`
Expected: 4 passed.

- [ ] **Step 5: Final full-suite gate**

Run all checks:

```bash
pytest -q
ruff check src tests
mypy --strict src
```

Expected: every command exits 0.

- [ ] **Step 6: Commit**

```bash
git add src/spacefleet/core/events.py tests/test_events.py
git commit -m "feat(core): add typed event bus"
```

---

# Self-Review

**Spec coverage:**
- Sprint 1 — `models/loadout.py` (Task 1), `data/upgrade_registry.py` (Task 2). All other Sprint 1 modules already exist.
- Sprint 2 — `models/fleet.py` (Task 3), `models/morale.py` (Task 4), `models/subsystems.py` (Task 5), `models/stance.py` (Task 6), `spatial/movement.py` (Task 7), `phases/movement_phase.py` (Task 8). `models/ship.py` already exists.
- Sprint 3 — `combat/gunnery.py` (Task 9), `combat/lance.py` (Task 10), `combat/damage.py` (Task 11), `combat/morale_effects.py` (Task 12), `phases/shooting_phase.py` (Task 13). `combat/critical_hits.py` and `combat/boarding.py` already exist.
- Sprint 4 — `core/game_state.py` (Task 14), `core/events.py` (Task 15). `core/game_loop.py`, `cli/*` and `__main__.py` already exist.

**Type consistency:** `MoveOrder` (Task 8) is consumed only inside its own module. `FireOrder` (Task 13) only inside its own. `Loadout` (Task 1) is independent. `CoreGameState` (Task 14) and `EventBus` (Task 15) are new public types. No cross-task signature drift.

**Placeholder scan:** Every step contains complete code. The one optional swap in Task 11 Step 5 is explicitly marked optional with a fallback path that keeps the existing tests green.

---

# Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-13-sprint1-4-gap-fill.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
