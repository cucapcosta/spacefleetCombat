# Fleet Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Custom fleet assembly within a points budget — spec model + validation, JSON persistence, battle assembly (`create_pve_custom`), and the interactive CLI fleet builder.

**Architecture:** Four layers: `models/fleet_spec.py` (serializable spec + points + validation reusing `Loadout.validate`/`validate_upgrades`/`doctrine_allows_weapon`), `persistence/fleet_save.py` (JSON save/load), `net/game_state.py` additions (`add_custom_fleet`, `create_pve_custom`, flagship override), `cli/fleet_builder_cmd.py` (`FleetBuilderSession` testable interpreter + REPL wrapper, wired into the app menu).

**Tech Stack:** Python 3.12, uv, pytest, ruff, mypy --strict.

**Spec:** `docs/superpowers/specs/2026-08-04-fleet-builder-design.md`

## Global Constraints

- Gate before every commit: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q`
- All pre-existing tests stay green (295 at branch start).
- Commit messages human-authored, no AI attribution, prefixes `feat(fleet):` / `test(fleet):` / `fix(fleet):`.
- Points formula: `hull_cost + sum(weapon costs) + sum(upgrade costs) + doctrine cost`. Budget default 1000.
- Validation REUSES existing helpers — do not duplicate slot/upgrade/doctrine rules.

---

## File Structure

- **Create** `src/spacefleet/models/fleet_spec.py` — ShipSpec/FleetSpec, points, validation, dict round-trip, default loadout.
- **Modify** `src/spacefleet/data/hull_registry.py` — `default_loadout(hull_id)` parallel store.
- **Create** `src/spacefleet/persistence/fleet_save.py` — JSON save/load.
- **Modify** `src/spacefleet/net/game_state.py` — `add_custom_fleet`, `GameState.create_pve_custom`, `_assign_default_commander(flagship_override=...)`.
- **Create** `src/spacefleet/cli/fleet_builder_cmd.py` — `FleetBuilderSession` + `run_fleet_builder`.
- **Modify** `src/spacefleet/cli/app.py` — menu `[3] Fleet Builder`.
- **Modify** `docs/docs/design/ship-customization.md` — implementation-status note.
- **Create** tests: `tests/test_fleet_spec.py`, `tests/test_fleet_spec_validation.py`, `tests/test_fleet_save.py`, `tests/test_custom_fleet_assembly.py`, `tests/test_fleet_builder_cli.py`.

## Reference: existing APIs (verified 2026-08-04)

- `HullRegistry` (`data/hull_registry.py`): `get`, `get_or_none`, `all`, `by_faction(faction)`, `by_class`, `reset`; `_load` parses yamls from `data/ships/*/*.yaml` via `_parse_hull(raw)`; the raw dict has top-level `default_loadout: {weapons: {slot_id: weapon_id}, upgrades: [...], doctrine: id|null}` which is currently DROPPED. Real hull ids: imperial `cobra_destroyer, dauntless_light_cruiser, emperor_battleship, lunar_cruiser, mars_battlecruiser, sword_frigate`; chaos `desolator_battleship, iconoclast_destroyer, murder_cruiser, slaughter_cruiser`.
- `HullProfile` (frozen): `id, name, classification: ShipClass, faction: Faction, hull_cost: int, leadership, hull_hits, armor_*, speed, turn_rate, shields, turrets, sensor_range, weapon_slots: tuple[WeaponSlotDef, ...], assault_actions=0, base_morale=100`. `WeaponSlotDef`: `id: int, name: str, arc: Arc, size: WeaponSize, allowed_types: tuple[WeaponType, ...]`.
- `WeaponRegistry`: `get`, `get_or_none`, `all`, `reset`. `WeaponProfile` (frozen): `id, name, weapon_type, size, strength, range, cost, description="", speed=0, critical_chance_bonus=0.0, damage_per_hit=1, ignores_armor=False`. Catalog ids include `macro_cannon_1/2/3/4, mars_pattern_battery, ryza_pattern_battery, lance_1/2/3, disruption_lance, standard_torpedoes, guided_torpedoes, melta_torpedoes, boarding_torpedoes, nova_cannon`.
- `DoctrineRegistry`: `get`, `get_or_none(id_or_none)`, `all`, `for_faction(faction)`, `reset`. `DoctrineDef.faction: str` (compares to `Faction.value`), `.cost: int`, `.upgrade_slot_bonus`, `.lances_allowed`.
- `UpgradeRegistry`: `get`, `get_or_none`, `all`, `reset`; `UpgradeProfile.cost: int`, `.flagship_only: bool`.
- `Loadout` (`models/loadout.py`): `Loadout(weapons: list[WeaponMount], upgrade_ids=[], doctrine_id=None)`; `.validate(hull)` raises `LoadoutError(ValueError)` on unknown slot / disallowed type / oversize; `.total_cost()` sums weapon costs only.
- `doctrine_allows_weapon(doctrine: DoctrineDef, weapon: WeaponProfile) -> bool` (`commander/doctrine_effects.py`).
- `validate_upgrades(hull, upgrade_ids, *, doctrine_id=None, is_flagship=False)` raises `LoadoutError` (`commander/upgrade_effects.py`); `build_ship_with_upgrades(ship_id, name, hull, weapons, *, upgrade_ids, doctrine_id=None, position=None, heading=0.0) -> Ship`.
- `WeaponMount(slot_id: int, slot_name: str, arc: Arc, weapon: WeaponProfile)`.
- `Faction` enum: `IMPERIAL_NAVY` (`"imperial_navy"`), `CHAOS_FLEET` (`"chaos_fleet"`). Construct from value: `Faction("imperial_navy")`.
- `net/game_state.py`: `_assign_default_commander(state, fleet_id, ship_ids, faction)` — picks flagship via `_CLASS_WEIGHT`, builds starter commander, calls `apply_flagship_upgrade_charges(cmdr, flagship)` (added by the upgrade-effects branch), constructs `Fleet(id=..., commander=..., flagship_ship_id=..., ship_ids=..., commander_name=..., ships=...)`. Factories `create_pve/create_pvp/create_mixed` follow the pattern `state = cls(dice=DiceRoller(seed=seed))` then `_add_*` helpers then `return state`. `_add_ai_hulks(state, num_hulks=2, ...)` exists. `state.player_ships: dict[str, list[str]]`, `state.kills: dict[str, int]`, `state.add_ship(ship)` exists on core state.
- `get_data_dir() -> Path | None` (`data/loader.py`); honors `SPACEFLEET_DATA_DIR` env var.
- `cli/prompts.py`: `prompt_with_default(label, default) -> str | None`, `prompt_required(label) -> str | None`, `prompt_int(label, default, *, min_val=1, max_val=65535) -> int | None` — all return None on Ctrl-C/D. `cli/colors.py`: `C`, `bold`, `colored`, `dim`.
- `cli/app.py`: `MENU` string has `[3] Configuration (not yet available)`; `main()` dispatches `choice == "3"` to a dead print.
- `resolve_turn(state, {ship_id: Command(ship_id=..., action="pass", args={})})` for integration smoke; `from spacefleet.net.commands import Command`.
- Registries cache at class level — tests that depend on yaml content call `.reset()` first.
- Lunar cruiser slots (from `data/ships/imperial/lunar_cruiser.yaml`): verify with a quick read before writing assembly tests; sword_frigate has 2 small PROW battery slots (ids 1, 2) and `hull_cost` per its yaml.

---

## Task 1: ShipSpec / FleetSpec + points + dict round-trip

**Files:**
- Create: `src/spacefleet/models/fleet_spec.py`
- Test: `tests/test_fleet_spec.py`

**Interfaces:**
- Produces: `ShipSpec`, `FleetSpec`, `FleetSpecError(ValueError)`, `ship_points(ShipSpec) -> int`, `fleet_points(FleetSpec) -> int`, `fleet_to_dict(FleetSpec) -> dict`, `fleet_from_dict(dict) -> FleetSpec`.

- [ ] **Step 1: Write the failing test**

```python
"""FleetSpec model — points math and dict round-trip."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    ShipSpec,
    fleet_from_dict,
    fleet_points,
    fleet_to_dict,
    ship_points,
)


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def _lunar() -> ShipSpec:
    return ShipSpec(
        name="ISS Hammer",
        hull_id="lunar_cruiser",
        weapons={1: "macro_cannon_3", 2: "macro_cannon_3"},
        upgrade_ids=["armour_piercing_ammo"],
        doctrine_id="navy_gunnery_school",
    )


def test_ship_points_is_hull_plus_parts() -> None:
    spec = _lunar()
    hull = HullRegistry.get("lunar_cruiser")
    expected = (
        hull.hull_cost
        + 2 * WeaponRegistry.get("macro_cannon_3").cost
        + UpgradeRegistry.get("armour_piercing_ammo").cost
        + DoctrineRegistry.get("navy_gunnery_school").cost
    )
    assert ship_points(spec) == expected


def test_ship_points_bare_hull() -> None:
    spec = ShipSpec(name="Bare", hull_id="sword_frigate")
    assert ship_points(spec) == HullRegistry.get("sword_frigate").hull_cost


def test_ship_points_unknown_ids_raise() -> None:
    with pytest.raises(FleetSpecError, match="unknown hull"):
        ship_points(ShipSpec(name="X", hull_id="starfort"))
    with pytest.raises(FleetSpecError, match="unknown weapon"):
        ship_points(ShipSpec(name="X", hull_id="sword_frigate", weapons={1: "railgun"}))
    with pytest.raises(FleetSpecError, match="unknown upgrade"):
        ship_points(ShipSpec(name="X", hull_id="sword_frigate", upgrade_ids=["cloak"]))
    with pytest.raises(FleetSpecError, match="unknown doctrine"):
        ship_points(ShipSpec(name="X", hull_id="sword_frigate", doctrine_id="mark_of_ork"))


def test_fleet_points_sums_ships() -> None:
    fleet = FleetSpec(
        name="Battlefleet",
        faction=Faction.IMPERIAL_NAVY,
        ships=[_lunar(), ShipSpec(name="Bare", hull_id="sword_frigate")],
    )
    assert fleet_points(fleet) == ship_points(fleet.ships[0]) + ship_points(fleet.ships[1])


def test_dict_round_trip() -> None:
    fleet = FleetSpec(
        name="Battlefleet",
        faction=Faction.IMPERIAL_NAVY,
        ships=[_lunar()],
        flagship_index=0,
    )
    data = fleet_to_dict(fleet)
    # JSON-safe: weapons keys become strings on the wire
    import json

    restored = fleet_from_dict(json.loads(json.dumps(data)))
    assert restored == fleet
    assert restored.ships[0].weapons == {1: "macro_cannon_3", 2: "macro_cannon_3"}
    assert restored.faction is Faction.IMPERIAL_NAVY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fleet_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spacefleet.models.fleet_spec'`

- [ ] **Step 3: Implement**

Create `src/spacefleet/models/fleet_spec.py`:

```python
"""Serializable fleet/ship build specs — points math, validation, round-trip.

A *spec* describes what a player bought (hull, weapons per slot, upgrades,
doctrine); it carries no runtime state.  ``net.game_state.add_custom_fleet``
materialises specs into ships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry


class FleetSpecError(ValueError):
    """Raised when a fleet/ship spec references unknown ids or breaks rules."""


@dataclass
class ShipSpec:
    """One ship build: hull + weapon choices per slot + upgrades + doctrine."""

    name: str
    hull_id: str
    weapons: dict[int, str] = field(default_factory=dict)  # slot_id -> weapon_id
    upgrade_ids: list[str] = field(default_factory=list)
    doctrine_id: str | None = None


@dataclass
class FleetSpec:
    """A named, faction-pure list of ship builds with a designated flagship."""

    name: str
    faction: Faction
    ships: list[ShipSpec] = field(default_factory=list)
    flagship_index: int = 0


def ship_points(spec: ShipSpec) -> int:
    """hull_cost + weapon costs + upgrade costs + doctrine cost."""
    hull = HullRegistry.get_or_none(spec.hull_id)
    if hull is None:
        raise FleetSpecError(f"unknown hull id {spec.hull_id!r}")
    total = hull.hull_cost
    for slot_id, weapon_id in spec.weapons.items():
        weapon = WeaponRegistry.get_or_none(weapon_id)
        if weapon is None:
            raise FleetSpecError(f"unknown weapon id {weapon_id!r} (slot {slot_id})")
        total += weapon.cost
    for upgrade_id in spec.upgrade_ids:
        upgrade = UpgradeRegistry.get_or_none(upgrade_id)
        if upgrade is None:
            raise FleetSpecError(f"unknown upgrade id {upgrade_id!r}")
        total += upgrade.cost
    if spec.doctrine_id is not None:
        doctrine = DoctrineRegistry.get_or_none(spec.doctrine_id)
        if doctrine is None:
            raise FleetSpecError(f"unknown doctrine id {spec.doctrine_id!r}")
        total += doctrine.cost
    return total


def fleet_points(fleet: FleetSpec) -> int:
    """Total points across all ships."""
    return sum(ship_points(s) for s in fleet.ships)


def fleet_to_dict(fleet: FleetSpec) -> dict[str, Any]:
    """JSON-safe dict (weapon slot keys serialise as strings)."""
    return {
        "name": fleet.name,
        "faction": fleet.faction.value,
        "flagship_index": fleet.flagship_index,
        "ships": [
            {
                "name": s.name,
                "hull_id": s.hull_id,
                "weapons": {str(k): v for k, v in s.weapons.items()},
                "upgrade_ids": list(s.upgrade_ids),
                "doctrine_id": s.doctrine_id,
            }
            for s in fleet.ships
        ],
    }


def fleet_from_dict(data: dict[str, Any]) -> FleetSpec:
    """Inverse of :func:`fleet_to_dict`; coerces weapon slot keys back to int."""
    try:
        ships = [
            ShipSpec(
                name=str(raw["name"]),
                hull_id=str(raw["hull_id"]),
                weapons={int(k): str(v) for k, v in (raw.get("weapons") or {}).items()},
                upgrade_ids=[str(u) for u in (raw.get("upgrade_ids") or [])],
                doctrine_id=raw.get("doctrine_id"),
            )
            for raw in data.get("ships", [])
        ]
        return FleetSpec(
            name=str(data["name"]),
            faction=Faction(str(data["faction"])),
            ships=ships,
            flagship_index=int(data.get("flagship_index", 0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise FleetSpecError(f"malformed fleet data: {exc}") from exc
```

Note: a `Faction("bad_value")` raises `ValueError`, which the except clause wraps into `FleetSpecError` — intended.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fleet_spec.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/models/fleet_spec.py tests/test_fleet_spec.py
git commit -m "feat(fleet): ship/fleet build specs with points math"
```

---

## Task 2: Spec validation (weapons, doctrine, upgrades, fleet rules)

**Files:**
- Modify: `src/spacefleet/models/fleet_spec.py`
- Test: `tests/test_fleet_spec_validation.py`

**Interfaces:**
- Consumes: `Loadout.validate`, `doctrine_allows_weapon`, `validate_upgrades`.
- Produces: `validate_ship_spec(spec: ShipSpec, faction: Faction, *, is_flagship: bool = False) -> None`; `validate_fleet_spec(fleet: FleetSpec, *, budget: int | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
"""FleetSpec validation — reuses loadout/upgrade/doctrine rules."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    ShipSpec,
    fleet_points,
    validate_fleet_spec,
    validate_ship_spec,
)
from spacefleet.models.loadout import LoadoutError


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def test_valid_ship_passes() -> None:
    spec = ShipSpec(
        name="OK",
        hull_id="sword_frigate",
        weapons={1: "macro_cannon_1", 2: "macro_cannon_1"},
        upgrade_ids=["reinforced_prow"],
        doctrine_id="commissariat",
    )
    validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_hull_faction_must_match_fleet() -> None:
    spec = ShipSpec(name="Traitor", hull_id="murder_cruiser")
    with pytest.raises(FleetSpecError, match="faction"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_weapon_slot_rules_enforced() -> None:
    # sword_frigate slots are SMALL battery mounts: a medium gun must not fit
    spec = ShipSpec(name="Big gun", hull_id="sword_frigate", weapons={1: "macro_cannon_3"})
    with pytest.raises(LoadoutError):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_doctrine_faction_lock() -> None:
    spec = ShipSpec(name="Heretic", hull_id="sword_frigate", doctrine_id="mark_of_khorne")
    with pytest.raises(FleetSpecError, match="faction"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_khorne_lance_ban() -> None:
    # iconoclast_destroyer is a chaos escort; find a slot that accepts a small lance
    spec = ShipSpec(
        name="Khorne", hull_id="iconoclast_destroyer", weapons={1: "lance_1"},
        doctrine_id="mark_of_khorne",
    )
    with pytest.raises(FleetSpecError, match="lance"):
        validate_ship_spec(spec, Faction.CHAOS_FLEET)


def test_upgrade_slot_cap_via_existing_validator() -> None:
    spec = ShipSpec(
        name="Overloaded",
        hull_id="sword_frigate",  # escort: 1 upgrade slot
        upgrade_ids=["reinforced_prow", "crew_quarters"],
    )
    with pytest.raises(LoadoutError, match="slots"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY)


def test_flagship_only_upgrade_gated() -> None:
    spec = ShipSpec(name="Nav", hull_id="sword_frigate", upgrade_ids=["navigators_chamber"])
    with pytest.raises(LoadoutError, match="flagship"):
        validate_ship_spec(spec, Faction.IMPERIAL_NAVY, is_flagship=False)
    validate_ship_spec(spec, Faction.IMPERIAL_NAVY, is_flagship=True)  # ok


def _two_ship_fleet() -> FleetSpec:
    return FleetSpec(
        name="BF Calixis",
        faction=Faction.IMPERIAL_NAVY,
        ships=[
            ShipSpec(name="Flag", hull_id="dauntless_light_cruiser"),
            ShipSpec(name="Escort", hull_id="sword_frigate"),
        ],
        flagship_index=0,
    )


def test_valid_fleet_passes_with_budget() -> None:
    fleet = _two_ship_fleet()
    validate_fleet_spec(fleet, budget=fleet_points(fleet))


def test_fleet_rules() -> None:
    with pytest.raises(FleetSpecError, match="at least one ship"):
        validate_fleet_spec(FleetSpec(name="Empty", faction=Faction.IMPERIAL_NAVY))
    bad_flag = _two_ship_fleet()
    bad_flag.flagship_index = 5
    with pytest.raises(FleetSpecError, match="flagship"):
        validate_fleet_spec(bad_flag)
    dup = _two_ship_fleet()
    dup.ships[1].name = "Flag"
    with pytest.raises(FleetSpecError, match="duplicate ship name"):
        validate_fleet_spec(dup)


def test_fleet_budget_enforced() -> None:
    fleet = _two_ship_fleet()
    with pytest.raises(FleetSpecError, match="budget"):
        validate_fleet_spec(fleet, budget=fleet_points(fleet) - 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fleet_spec_validation.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_ship_spec'`

Pre-check note for the implementer: read `data/ships/chaos/iconoclast_destroyer.yaml` first — the Khorne test needs a slot on it that accepts a small lance (`lance_1`). If slot 1 doesn't allow lances, pick whichever slot does (adjust the slot key in the test), or switch the test hull to `murder_cruiser` with the correct slot id. The assertion target (`FleetSpecError` mentioning "lance") stays the same.

- [ ] **Step 3: Implement** (append to `fleet_spec.py`)

```python
def validate_ship_spec(
    spec: ShipSpec,
    faction: Faction,
    *,
    is_flagship: bool = False,
) -> None:
    """Validate one ship build against hull, weapon, doctrine and upgrade rules.

    Raises :class:`FleetSpecError` for spec-level violations and lets
    :class:`~spacefleet.models.loadout.LoadoutError` propagate for slot and
    upgrade-cap violations (both are ``ValueError``).
    """
    from spacefleet.commander.doctrine_effects import doctrine_allows_weapon
    from spacefleet.commander.upgrade_effects import validate_upgrades
    from spacefleet.models.loadout import Loadout
    from spacefleet.models.weapon import WeaponMount

    hull = HullRegistry.get_or_none(spec.hull_id)
    if hull is None:
        raise FleetSpecError(f"unknown hull id {spec.hull_id!r}")
    if hull.faction is not faction:
        raise FleetSpecError(
            f"hull {spec.hull_id!r} belongs to faction {hull.faction.value!r},"
            f" not {faction.value!r}"
        )

    slot_index = {s.id: s for s in hull.weapon_slots}
    mounts: list[WeaponMount] = []
    for slot_id, weapon_id in sorted(spec.weapons.items()):
        weapon = WeaponRegistry.get_or_none(weapon_id)
        if weapon is None:
            raise FleetSpecError(f"unknown weapon id {weapon_id!r} (slot {slot_id})")
        slot = slot_index.get(slot_id)
        name = slot.name if slot is not None else f"slot {slot_id}"
        arc = slot.arc if slot is not None else hull.weapon_slots[0].arc
        mounts.append(WeaponMount(slot_id=slot_id, slot_name=name, arc=arc, weapon=weapon))
    Loadout(weapons=mounts).validate(hull)

    doctrine = None
    if spec.doctrine_id is not None:
        doctrine = DoctrineRegistry.get_or_none(spec.doctrine_id)
        if doctrine is None:
            raise FleetSpecError(f"unknown doctrine id {spec.doctrine_id!r}")
        if doctrine.faction != faction.value:
            raise FleetSpecError(
                f"doctrine {spec.doctrine_id!r} belongs to faction {doctrine.faction!r},"
                f" not {faction.value!r}"
            )
        for mount in mounts:
            if not doctrine_allows_weapon(doctrine, mount.weapon):
                raise FleetSpecError(
                    f"doctrine {spec.doctrine_id!r} forbids lance weapon"
                    f" {mount.weapon.id!r}"
                )

    validate_upgrades(
        hull,
        spec.upgrade_ids,
        doctrine_id=spec.doctrine_id,
        is_flagship=is_flagship,
    )


def validate_fleet_spec(fleet: FleetSpec, *, budget: int | None = None) -> None:
    """Validate the whole fleet: composition rules, per-ship rules, budget."""
    if not fleet.ships:
        raise FleetSpecError("fleet needs at least one ship")
    if not (0 <= fleet.flagship_index < len(fleet.ships)):
        raise FleetSpecError(
            f"flagship index {fleet.flagship_index} out of range"
            f" (fleet has {len(fleet.ships)} ships)"
        )
    names = [s.name for s in fleet.ships]
    if len(set(names)) != len(names):
        raise FleetSpecError(f"duplicate ship name in {names}")
    for idx, ship in enumerate(fleet.ships):
        validate_ship_spec(ship, fleet.faction, is_flagship=(idx == fleet.flagship_index))
    if budget is not None:
        total = fleet_points(fleet)
        if total > budget:
            raise FleetSpecError(f"fleet costs {total} pts, over budget {budget}")
```

Note on the unknown-slot path: when `slot_id` isn't in `slot_index`, a placeholder mount is still built so `Loadout.validate` raises its canonical "unknown slot id" `LoadoutError` — do not pre-empt it with a `FleetSpecError`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fleet_spec_validation.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/models/fleet_spec.py tests/test_fleet_spec_validation.py
git commit -m "feat(fleet): ship and fleet spec validation"
```

---

## Task 3: `HullRegistry.default_loadout` + `apply_default_loadout`

**Files:**
- Modify: `src/spacefleet/data/hull_registry.py`
- Modify: `src/spacefleet/models/fleet_spec.py`
- Test: `tests/test_fleet_spec.py` (append)

**Interfaces:**
- Produces: `HullRegistry.default_loadout(hull_id: str) -> dict[str, Any]` (empty dict when absent/unknown); `apply_default_loadout(spec: ShipSpec) -> None` (mutates spec in place from the hull's yaml `default_loadout`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_fleet_spec.py`)

```python
from spacefleet.models.fleet_spec import apply_default_loadout


def test_hull_registry_exposes_default_loadout() -> None:
    dl = HullRegistry.default_loadout("cobra_destroyer")
    assert dl["weapons"] == {1: "macro_cannon_1", 2: "standard_torpedoes"}
    assert dl["upgrades"] == []
    assert dl["doctrine"] is None
    assert HullRegistry.default_loadout("no_such_hull") == {}


def test_apply_default_loadout_fills_spec() -> None:
    spec = ShipSpec(name="Cobra", hull_id="cobra_destroyer")
    apply_default_loadout(spec)
    assert spec.weapons == {1: "macro_cannon_1", 2: "standard_torpedoes"}
    assert spec.upgrade_ids == []
    assert spec.doctrine_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fleet_spec.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'default_loadout'`

- [ ] **Step 3: Implement**

`hull_registry.py`: read the current `_load` implementation first. Add a class attr `_default_loadouts: dict[str, dict[str, Any]] = {}`. Where `_load` successfully parses a hull from a raw yaml dict, also store (weapon keys coerced to int, missing sections normalised):

```python
            raw_dl = raw.get("default_loadout") or {}
            cls._default_loadouts[hull.id] = {
                "weapons": {int(k): str(v) for k, v in (raw_dl.get("weapons") or {}).items()},
                "upgrades": [str(u) for u in (raw_dl.get("upgrades") or [])],
                "doctrine": raw_dl.get("doctrine"),
            }
```

Add classmethod:

```python
    @classmethod
    def default_loadout(cls, hull_id: str) -> dict[str, Any]:
        """The hull's yaml ``default_loadout`` (weapons/upgrades/doctrine), or {}."""
        cls._load()
        return dict(cls._default_loadouts.get(hull_id, {}))
```

Clear `_default_loadouts` in `reset()` (and re-init in `_load` alongside the hull dict if `_load` reassigns it). The demo fallback path stores nothing (lookups return `{}`).

`fleet_spec.py` — append:

```python
def apply_default_loadout(spec: ShipSpec) -> None:
    """Fill *spec* with the hull's yaml default loadout (overwrites choices)."""
    default = HullRegistry.default_loadout(spec.hull_id)
    if not default:
        return
    spec.weapons = dict(default.get("weapons") or {})
    spec.upgrade_ids = list(default.get("upgrades") or [])
    spec.doctrine_id = default.get("doctrine")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fleet_spec.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/data/hull_registry.py src/spacefleet/models/fleet_spec.py tests/test_fleet_spec.py
git commit -m "feat(fleet): expose hull default loadouts from the registry"
```

---

## Task 4: JSON persistence

**Files:**
- Create: `src/spacefleet/persistence/fleet_save.py`
- Test: `tests/test_fleet_save.py`

**Interfaces:**
- Consumes: `fleet_to_dict` / `fleet_from_dict` / `FleetSpecError`.
- Produces: `save_fleet(fleet: FleetSpec, path: Path) -> Path`, `load_fleet(path: Path) -> FleetSpec`, `default_fleet_dir() -> Path`.

- [ ] **Step 1: Write the failing test**

```python
"""Fleet save/load — JSON round-trip and error handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from spacefleet.core.types import Faction
from spacefleet.models.fleet_spec import FleetSpec, FleetSpecError, ShipSpec
from spacefleet.persistence.fleet_save import default_fleet_dir, load_fleet, save_fleet


def _fleet() -> FleetSpec:
    return FleetSpec(
        name="BF Test",
        faction=Faction.IMPERIAL_NAVY,
        ships=[
            ShipSpec(
                name="Flag",
                hull_id="dauntless_light_cruiser",
                weapons={1: "macro_cannon_3"},
                upgrade_ids=["reinforced_prow"],
                doctrine_id="commissariat",
            )
        ],
    )


def test_save_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "bf_test.json"
    written = save_fleet(_fleet(), path)
    assert written == path
    assert load_fleet(path) == _fleet()


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "f.json"
    save_fleet(_fleet(), path)
    assert path.exists()


def test_load_missing_file_raises() -> None:
    with pytest.raises(FleetSpecError, match="no such fleet file"):
        load_fleet(Path("/nonexistent/fleet.json"))


def test_load_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FleetSpecError, match="not valid JSON"):
        load_fleet(path)


def test_default_fleet_dir_is_a_path() -> None:
    d = default_fleet_dir()
    assert d.name == "fleets"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fleet_save.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spacefleet.persistence.fleet_save'`

- [ ] **Step 3: Implement**

Create `src/spacefleet/persistence/fleet_save.py`:

```python
"""Fleet spec persistence — plain-JSON save files (stdlib only)."""

from __future__ import annotations

import json
from pathlib import Path

from spacefleet.data.loader import get_data_dir
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    fleet_from_dict,
    fleet_to_dict,
)


def default_fleet_dir() -> Path:
    """``data/fleets`` when the data dir exists, else ``./fleets``."""
    data_dir = get_data_dir()
    base = data_dir if data_dir is not None else Path.cwd()
    return base / "fleets"


def save_fleet(fleet: FleetSpec, path: Path) -> Path:
    """Write *fleet* as pretty JSON, creating parent dirs. Returns *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(fleet_to_dict(fleet), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_fleet(path: Path) -> FleetSpec:
    """Read a fleet JSON file. Raises :class:`FleetSpecError` on any failure."""
    if not path.is_file():
        raise FleetSpecError(f"no such fleet file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FleetSpecError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FleetSpecError(f"{path} is not a fleet file (expected a JSON object)")
    return fleet_from_dict(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fleet_save.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/persistence/fleet_save.py tests/test_fleet_save.py
git commit -m "feat(fleet): JSON fleet save/load"
```

---

## Task 5: Battle assembly — `add_custom_fleet` + `create_pve_custom`

**Files:**
- Modify: `src/spacefleet/net/game_state.py`
- Test: `tests/test_custom_fleet_assembly.py`

**Interfaces:**
- Consumes: `validate_fleet_spec`, `build_ship_with_upgrades`, `_assign_default_commander`, `_add_ai_hulks`.
- Produces: `add_custom_fleet(state: GameState, player_id: str, fleet: FleetSpec, *, start_x: float = 0.0, start_y: float = 0.0, heading: float = 0.0) -> list[str]`; `GameState.create_pve_custom(player_id: str, fleet: FleetSpec, *, seed: int | None = None, num_hulks: int = 4) -> GameState`; `_assign_default_commander(..., flagship_override: str | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
"""Custom fleet assembly into a live GameState."""

from __future__ import annotations

import pytest

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import FleetSpec, FleetSpecError, ShipSpec
from spacefleet.net.game_state import GameState, add_custom_fleet


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def _fleet() -> FleetSpec:
    return FleetSpec(
        name="BF Custom",
        faction=Faction.IMPERIAL_NAVY,
        ships=[
            ShipSpec(
                name="ISS Flag",
                hull_id="dauntless_light_cruiser",
                weapons={1: "macro_cannon_3", 2: "macro_cannon_3"},
                upgrade_ids=["additional_void_shield", "navigators_chamber"],
                doctrine_id="commissariat",
            ),
            ShipSpec(
                name="ISS Escort",
                hull_id="sword_frigate",
                weapons={1: "macro_cannon_1"},
            ),
        ],
        flagship_index=0,
    )


def test_assembly_materialises_specs() -> None:
    state = GameState()
    ship_ids = add_custom_fleet(state, "paulo", _fleet())
    assert len(ship_ids) == 2
    assert state.player_ships["paulo"] == ship_ids

    flag = state.ships[ship_ids[0]]
    assert flag.name == "ISS Flag"
    assert flag.doctrine_id == "commissariat"
    assert flag.morale_floor == 20  # doctrine applied via build_ship_with_upgrades
    assert flag.shields_max == HullRegistry.get("dauntless_light_cruiser").shields + 1
    assert [w.weapon.id for w in flag.weapons] == ["macro_cannon_3", "macro_cannon_3"]
    assert flag.faction is Faction.IMPERIAL_NAVY

    escort = state.ships[ship_ids[1]]
    assert escort.hull.id == "sword_frigate"
    assert len(escort.weapons) == 1


def test_assembly_sets_spec_flagship_and_charges() -> None:
    state = GameState()
    fleet_spec = _fleet()
    fleet_spec.flagship_index = 0
    ship_ids = add_custom_fleet(state, "paulo", fleet_spec)
    fleet = state.fleets["paulo"]
    assert fleet.flagship_ship_id == ship_ids[0]
    assert fleet.commander is not None


def test_assembly_rejects_invalid_fleet() -> None:
    state = GameState()
    bad = _fleet()
    bad.ships[1].name = "ISS Flag"  # duplicate name
    with pytest.raises(FleetSpecError):
        add_custom_fleet(state, "paulo", bad)
    assert "paulo" not in state.player_ships  # nothing half-assembled


def test_create_pve_custom_spawns_enemies() -> None:
    state = GameState.create_pve_custom("paulo", _fleet(), seed=42, num_hulks=3)
    assert len(state.player_ships["paulo"]) == 2
    assert len(state.ai_ships) == 3
    factions = {state.ships[s].faction for s in state.ai_ships}
    assert factions == {Faction.CHAOS_FLEET}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_custom_fleet_assembly.py -v`
Expected: FAIL — `ImportError: cannot import name 'add_custom_fleet'`

- [ ] **Step 3: Implement** (in `net/game_state.py`)

Change `_assign_default_commander` signature to accept `flagship_override: str | None = None`; flagship selection becomes:

```python
    if flagship_override is not None:
        flagship = state.ships[flagship_override]
    else:
        flagship = max(ships, key=lambda s: (_CLASS_WEIGHT.get(s.hull.classification, 0), s.id))
```

Add (module level, after `_make_default_weapons`; module-top imports: `from spacefleet.commander.upgrade_effects import build_ship_with_upgrades`, `from spacefleet.models.fleet_spec import FleetSpec, validate_fleet_spec` — check for cycles; if importing at module top creates one, use local imports inside the function, matching the file's existing style):

```python
def add_custom_fleet(
    state: GameState,
    player_id: str,
    fleet: FleetSpec,
    *,
    start_x: float = 0.0,
    start_y: float = 0.0,
    heading: float = 0.0,
) -> list[str]:
    """Materialise a validated :class:`FleetSpec` into *state* for *player_id*.

    Ships form a column behind the lead ship.  Returns the created ship ids.
    Raises before touching *state* if the spec is invalid.
    """
    validate_fleet_spec(fleet)

    ship_ids: list[str] = []
    for i, spec in enumerate(fleet.ships):
        hull = HullRegistry.get(spec.hull_id)
        slot_index = {s.id: s for s in hull.weapon_slots}
        mounts = [
            WeaponMount(
                slot_id=slot_id,
                slot_name=slot_index[slot_id].name,
                arc=slot_index[slot_id].arc,
                weapon=WeaponRegistry.get(weapon_id),
            )
            for slot_id, weapon_id in sorted(spec.weapons.items())
        ]
        ship_id = f"{player_id}_ship_{i + 1}"
        offset_x = -10.0 if i % 2 == 1 else (10.0 if i > 0 else 0.0)
        ship = build_ship_with_upgrades(
            ship_id,
            spec.name,
            hull,
            mounts,
            upgrade_ids=list(spec.upgrade_ids),
            doctrine_id=spec.doctrine_id,
            position=Vector2D(start_x + offset_x, start_y - 15.0 * i),
            heading=heading,
        )
        state.ships[ship_id] = ship
        ship_ids.append(ship_id)

    state.player_ships[player_id] = ship_ids
    state.kills[player_id] = 0
    _assign_default_commander(
        state,
        player_id,
        ship_ids,
        fleet.faction,
        flagship_override=ship_ids[fleet.flagship_index],
    )
    return ship_ids
```

And the factory on `GameState`:

```python
    @classmethod
    def create_pve_custom(
        cls,
        player_id: str,
        fleet: FleetSpec,
        *,
        seed: int | None = None,
        num_hulks: int = 4,
    ) -> GameState:
        """One player's custom fleet vs AI hulks."""
        state = cls(dice=DiceRoller(seed=seed))
        add_custom_fleet(state, player_id, fleet)
        _add_ai_hulks(state, num_hulks=num_hulks)
        return state
```

(`FleetSpec` in the classmethod signature: import under `TYPE_CHECKING` if the runtime import would cycle; the string annotation plus `from __future__ import annotations` already present makes that safe.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_custom_fleet_assembly.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/net/game_state.py tests/test_custom_fleet_assembly.py
git commit -m "feat(fleet): assemble custom fleets into battle state"
```

---

## Task 6: `FleetBuilderSession` — top-level commands

**Files:**
- Create: `src/spacefleet/cli/fleet_builder_cmd.py`
- Test: `tests/test_fleet_builder_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `FleetBuilderSession(faction: Faction, budget: int = 1000, name: str = "My Fleet")` with `.execute(line: str) -> str`, `.done: bool`, `.remaining: int`, `.fleet: FleetSpec`. Top-level commands: `help`, `hulls`, `weapons`, `upgrades`, `doctrines`, `buy <hull_id> <name...>`, `remove <n>`, `status`, `done`. (`equip`, `save`, `load` land in Task 7.)

- [ ] **Step 1: Write the failing test**

```python
"""FleetBuilderSession — command interpreter, no I/O."""

from __future__ import annotations

from spacefleet.cli.fleet_builder_cmd import FleetBuilderSession
from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry


def setup_function() -> None:
    HullRegistry.reset()
    WeaponRegistry.reset()
    UpgradeRegistry.reset()
    DoctrineRegistry.reset()


def _session(budget: int = 1000) -> FleetBuilderSession:
    return FleetBuilderSession(Faction.IMPERIAL_NAVY, budget=budget)


def test_buy_adds_ship_and_charges_budget() -> None:
    s = _session()
    out = s.execute("buy sword_frigate ISS Blade")
    assert "ISS Blade" in out
    hull_cost = HullRegistry.get("sword_frigate").hull_cost
    assert s.remaining == 1000 - hull_cost
    assert s.fleet.ships[0].hull_id == "sword_frigate"


def test_buy_unknown_hull_errors_cleanly() -> None:
    s = _session()
    out = s.execute("buy starfort Fortress")
    assert "unknown hull" in out.lower()
    assert s.fleet.ships == []


def test_buy_wrong_faction_hull_rejected() -> None:
    s = _session()
    out = s.execute("buy murder_cruiser Traitor")
    assert "faction" in out.lower()
    assert s.fleet.ships == []


def test_buy_over_budget_rejected() -> None:
    s = _session(budget=10)
    out = s.execute("buy sword_frigate ISS Blade")
    assert "budget" in out.lower()
    assert s.fleet.ships == []
    assert s.remaining == 10


def test_remove_refunds() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    out = s.execute("remove 1")
    assert "removed" in out.lower()
    assert s.fleet.ships == []
    assert s.remaining == 1000


def test_status_lists_ships_and_budget() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    out = s.execute("status")
    assert "ISS Blade" in out
    assert str(s.remaining) in out


def test_catalogs_list_faction_items() -> None:
    s = _session()
    assert "sword_frigate" in s.execute("hulls")
    assert "murder_cruiser" not in s.execute("hulls")  # chaos hull hidden
    assert "macro_cannon_1" in s.execute("weapons")
    assert "reinforced_prow" in s.execute("upgrades")
    doctrines = s.execute("doctrines")
    assert "commissariat" in doctrines
    assert "mark_of_khorne" not in doctrines  # chaos doctrine hidden


def test_done_flag_and_unknown_command() -> None:
    s = _session()
    assert "unknown command" in s.execute("frobnicate").lower()
    assert not s.done
    s.execute("done")
    assert s.done
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fleet_builder_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spacefleet.cli.fleet_builder_cmd'`

- [ ] **Step 3: Implement**

Create `src/spacefleet/cli/fleet_builder_cmd.py` (structure below; keep output plain strings — colors optional via `cli.colors` but tests assert substrings only):

```python
"""Interactive fleet builder — testable command interpreter + REPL wrapper.

``FleetBuilderSession.execute`` maps one input line to one output string and
never touches stdin/stdout, so tests drive it directly.  ``run_fleet_builder``
is the thin I/O loop the app menu calls.
"""

from __future__ import annotations

from spacefleet.core.types import Faction
from spacefleet.data.doctrine_registry import DoctrineRegistry
from spacefleet.data.hull_registry import HullRegistry
from spacefleet.data.upgrade_registry import UpgradeRegistry
from spacefleet.data.weapon_registry import WeaponRegistry
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    ShipSpec,
    fleet_points,
    ship_points,
    validate_ship_spec,
)

_HELP = """\
Commands:
  hulls | weapons | upgrades | doctrines   — browse catalogs
  buy <hull_id> <name...>                  — buy a hull
  equip <n>                                — configure ship n (see 'help' inside)
  remove <n>                               — sell ship n
  status                                   — fleet roster + budget
  save [path] | load <path>                — persist the fleet
  done                                     — finish
"""


class FleetBuilderSession:
    """State machine for one fleet-building session."""

    def __init__(
        self,
        faction: Faction,
        budget: int = 1000,
        name: str = "My Fleet",
    ) -> None:
        self.fleet = FleetSpec(name=name, faction=faction, ships=[])
        self.budget = budget
        self.done = False
        self._equip_index: int | None = None

    # ── Public API ────────────────────────────────────────────

    @property
    def remaining(self) -> int:
        return self.budget - fleet_points(self.fleet)

    def execute(self, line: str) -> str:
        parts = line.strip().split()
        if not parts:
            return ""
        cmd, args = parts[0].lower(), parts[1:]
        if self._equip_index is not None:
            return self._execute_equip(cmd, args)
        return self._execute_top(cmd, args)

    # ── Top-level commands ────────────────────────────────────

    def _execute_top(self, cmd: str, args: list[str]) -> str:
        if cmd == "help":
            return _HELP
        if cmd == "hulls":
            rows = [
                f"  {h.id:28s} {h.classification.value:14s} {h.hull_cost:4d} pts"
                for h in HullRegistry.by_faction(self.fleet.faction)
            ]
            return "\n".join(rows) or "  (no hulls)"
        if cmd == "weapons":
            rows = [
                f"  {w.id:24s} {w.weapon_type.value:10s} {w.size.value:8s}"
                f" str {w.strength:2d}  {w.cost:4d} pts"
                for w in WeaponRegistry.all().values()
            ]
            return "\n".join(rows)
        if cmd == "upgrades":
            rows = [
                f"  {u.id:28s} {u.cost:4d} pts  {u.name}"
                for u in UpgradeRegistry.all().values()
            ]
            return "\n".join(rows)
        if cmd == "doctrines":
            rows = [
                f"  {d.id:28s} {d.cost:4d} pts  {d.name}"
                for d in DoctrineRegistry.for_faction(self.fleet.faction)
            ]
            return "\n".join(rows)
        if cmd == "buy":
            return self._buy(args)
        if cmd == "remove":
            return self._remove(args)
        if cmd == "equip":
            return self._enter_equip(args)
        if cmd == "status":
            return self._status()
        if cmd == "save":
            return self._save(args)
        if cmd == "load":
            return self._load(args)
        if cmd in ("done", "quit", "exit"):
            self.done = True
            return f"Fleet '{self.fleet.name}' — {fleet_points(self.fleet)} pts."
        return f"unknown command: {cmd!r} (try 'help')"

    def _buy(self, args: list[str]) -> str:
        if len(args) < 2:
            return "usage: buy <hull_id> <name...>"
        hull_id, name = args[0], " ".join(args[1:])
        spec = ShipSpec(name=name, hull_id=hull_id)
        self.fleet.ships.append(spec)
        error = self._revalidate()
        if error:
            self.fleet.ships.pop()
            return error
        return (
            f"Bought {hull_id} as '{name}'."
            f" ({ship_points(spec)} pts — {self.remaining} remaining)"
        )

    def _remove(self, args: list[str]) -> str:
        idx = self._ship_index(args)
        if idx is None:
            return "usage: remove <ship number>"
        spec = self.fleet.ships.pop(idx)
        if self.fleet.flagship_index >= len(self.fleet.ships):
            self.fleet.flagship_index = 0
        return f"Removed '{spec.name}'. ({self.remaining} pts remaining)"

    def _status(self) -> str:
        if not self.fleet.ships:
            return f"Empty fleet. Budget: {self.budget} pts."
        rows = []
        for i, s in enumerate(self.fleet.ships):
            flag = " [FLAG]" if i == self.fleet.flagship_index else ""
            rows.append(f"  [{i + 1}] {s.name:24s} {s.hull_id:26s} {ship_points(s):4d} pts{flag}")
        rows.append(f"  Total {fleet_points(self.fleet)} / {self.budget} pts — {self.remaining} remaining")
        return "\n".join(rows)

    # ── Shared helpers ────────────────────────────────────────

    def _ship_index(self, args: list[str]) -> int | None:
        if len(args) != 1 or not args[0].isdigit():
            return None
        idx = int(args[0]) - 1
        if not (0 <= idx < len(self.fleet.ships)):
            return None
        return idx

    def _revalidate(self) -> str | None:
        """Validate the whole draft; return an error string or None."""
        try:
            for i, ship in enumerate(self.fleet.ships):
                validate_ship_spec(
                    ship,
                    self.fleet.faction,
                    is_flagship=(i == self.fleet.flagship_index),
                )
            if fleet_points(self.fleet) > self.budget:
                return (
                    f"over budget: {fleet_points(self.fleet)} > {self.budget} pts"
                )
        except (FleetSpecError, ValueError) as exc:
            return str(exc)
        return None
```

For this task, `_enter_equip`, `_execute_equip`, `_save`, `_load` are stubs returning `"(available after Task 7)"`-style strings is NOT acceptable — instead implement `_enter_equip`/`_execute_equip`/`_save`/`_load` as minimal placeholders that return `"not yet implemented"` **only if Task 7 is a separate commit**; since the reviewer gates each task, implement them here as raising-free stubs:

```python
    def _enter_equip(self, args: list[str]) -> str:
        return "not yet implemented"

    def _execute_equip(self, cmd: str, args: list[str]) -> str:
        return "not yet implemented"

    def _save(self, args: list[str]) -> str:
        return "not yet implemented"

    def _load(self, args: list[str]) -> str:
        return "not yet implemented"
```

(Task 7 replaces all four — the stubs exist so this task's surface is complete and typed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fleet_builder_cli.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/cli/fleet_builder_cmd.py tests/test_fleet_builder_cli.py
git commit -m "feat(fleet): fleet builder session with buy/remove/status"
```

---

## Task 7: Equip mode + save/load commands

**Files:**
- Modify: `src/spacefleet/cli/fleet_builder_cmd.py`
- Test: `tests/test_fleet_builder_cli.py` (append)

**Interfaces:**
- Produces: equip-mode commands `show`, `slot <n> <weapon_id>`, `unslot <n>`, `upgrade <id>`, `remove-upgrade <id>`, `doctrine <id|none>`, `flagship`, `default`, `back`; top-level `save [path]` / `load <path>` via `fleet_save`.

- [ ] **Step 1: Write the failing test** (append)

```python
from pathlib import Path


def test_equip_slot_upgrade_doctrine_flow() -> None:
    s = _session()
    s.execute("buy dauntless_light_cruiser ISS Flag")
    out = s.execute("equip 1")
    assert "ISS Flag" in out
    assert "slot 1 macro_cannon_3" != ""  # entering equip mode
    out = s.execute("slot 1 macro_cannon_3")
    assert "macro_cannon_3" in out
    out = s.execute("upgrade reinforced_prow")
    assert "reinforced_prow" in out
    out = s.execute("doctrine commissariat")
    assert "commissariat" in out
    out = s.execute("show")
    assert "macro_cannon_3" in out and "reinforced_prow" in out
    s.execute("back")
    ship = s.fleet.ships[0]
    assert ship.weapons[1] == "macro_cannon_3"
    assert ship.upgrade_ids == ["reinforced_prow"]
    assert ship.doctrine_id == "commissariat"


def test_equip_rejects_illegal_and_reverts() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    s.execute("equip 1")
    out = s.execute("slot 1 macro_cannon_3")  # medium gun in small slot
    assert "too large" in out or "not allowed" in out.lower() or "slot" in out.lower()
    assert s.fleet.ships[0].weapons == {}  # reverted


def test_unslot_and_remove_upgrade() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    s.execute("equip 1")
    s.execute("slot 1 macro_cannon_1")
    s.execute("upgrade reinforced_prow")
    s.execute("unslot 1")
    s.execute("remove-upgrade reinforced_prow")
    assert s.fleet.ships[0].weapons == {}
    assert s.fleet.ships[0].upgrade_ids == []


def test_default_command_applies_hull_kit() -> None:
    s = _session()
    s.execute("buy cobra_destroyer ISS Cobra")
    s.execute("equip 1")
    out = s.execute("default")
    assert "default" in out.lower()
    assert s.fleet.ships[0].weapons == {1: "macro_cannon_1", 2: "standard_torpedoes"}


def test_flagship_command() -> None:
    s = _session()
    s.execute("buy sword_frigate ISS One")
    s.execute("buy sword_frigate ISS Two")
    s.execute("equip 2")
    out = s.execute("flagship")
    assert "flagship" in out.lower()
    assert s.fleet.flagship_index == 1


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    path = tmp_path / "myfleet.json"
    out = s.execute(f"save {path}")
    assert str(path) in out
    s2 = _session()
    out = s2.execute(f"load {path}")
    assert "ISS Blade" in out or "loaded" in out.lower()
    assert s2.fleet.ships[0].name == "ISS Blade"


def test_load_over_budget_rejected(tmp_path: Path) -> None:
    s = _session()
    s.execute("buy sword_frigate ISS Blade")
    path = tmp_path / "f.json"
    s.execute(f"save {path}")
    tiny = FleetBuilderSession(Faction.IMPERIAL_NAVY, budget=5)
    out = tiny.execute(f"load {path}")
    assert "budget" in out.lower()
    assert tiny.fleet.ships == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fleet_builder_cli.py -v`
Expected: new tests FAIL on `"not yet implemented"` outputs

- [ ] **Step 3: Implement** — replace the four stubs:

```python
    def _enter_equip(self, args: list[str]) -> str:
        idx = self._ship_index(args)
        if idx is None:
            return "usage: equip <ship number>"
        self._equip_index = idx
        return f"Equipping '{self.fleet.ships[idx].name}' — {self._show_ship()}"

    def _execute_equip(self, cmd: str, args: list[str]) -> str:
        assert self._equip_index is not None
        ship = self.fleet.ships[self._equip_index]
        if cmd in ("back", "done"):
            self._equip_index = None
            return self._status()
        if cmd == "show":
            return self._show_ship()
        if cmd == "help":
            return (
                "Equip commands: show | slot <n> <weapon_id> | unslot <n>"
                " | upgrade <id> | remove-upgrade <id> | doctrine <id|none>"
                " | flagship | default | back"
            )
        if cmd == "slot" and len(args) == 2 and args[0].isdigit():
            return self._mutate(ship, lambda: ship.weapons.__setitem__(int(args[0]), args[1]),
                                f"Equipped {args[1]} in slot {args[0]}.")
        if cmd == "unslot" and len(args) == 1 and args[0].isdigit():
            slot = int(args[0])
            if slot not in ship.weapons:
                return f"slot {slot} is empty"
            return self._mutate(ship, lambda: ship.weapons.pop(slot),
                                f"Cleared slot {slot}.")
        if cmd == "upgrade" and len(args) == 1:
            if args[0] in ship.upgrade_ids:
                return f"{args[0]} already installed"
            return self._mutate(ship, lambda: ship.upgrade_ids.append(args[0]),
                                f"Installed {args[0]}.")
        if cmd == "remove-upgrade" and len(args) == 1:
            if args[0] not in ship.upgrade_ids:
                return f"{args[0]} is not installed"
            return self._mutate(ship, lambda: ship.upgrade_ids.remove(args[0]),
                                f"Removed {args[0]}.")
        if cmd == "doctrine" and len(args) == 1:
            new = None if args[0] in ("none", "clear") else args[0]
            return self._mutate(ship, lambda: setattr(ship, "doctrine_id", new),
                                f"Doctrine set to {new or 'none'}.")
        if cmd == "flagship":
            old = self.fleet.flagship_index
            self.fleet.flagship_index = self._equip_index
            error = self._revalidate()
            if error:
                self.fleet.flagship_index = old
                return error
            return f"'{ship.name}' is now the flagship."
        if cmd == "default":
            from spacefleet.models.fleet_spec import apply_default_loadout

            snapshot = (dict(ship.weapons), list(ship.upgrade_ids), ship.doctrine_id)
            apply_default_loadout(ship)
            error = self._revalidate()
            if error:
                ship.weapons, ship.upgrade_ids, ship.doctrine_id = (
                    dict(snapshot[0]), list(snapshot[1]), snapshot[2],
                )
                return error
            return f"Applied default loadout. ({ship_points(ship)} pts)"
        return f"unknown equip command: {cmd!r} (try 'help')"

    def _mutate(self, ship: ShipSpec, action: Callable[[], object], ok: str) -> str:
        """Apply a mutation transactionally: snapshot → act → validate → revert on error."""
        snapshot = (dict(ship.weapons), list(ship.upgrade_ids), ship.doctrine_id)
        action()
        error = self._revalidate()
        if error:
            ship.weapons, ship.upgrade_ids, ship.doctrine_id = (
                dict(snapshot[0]), list(snapshot[1]), snapshot[2],
            )
            return error
        return f"{ok} ({self.remaining} pts remaining)"

    def _show_ship(self) -> str:
        assert self._equip_index is not None
        ship = self.fleet.ships[self._equip_index]
        hull = HullRegistry.get_or_none(ship.hull_id)
        rows = [f"  {ship.name} ({ship.hull_id}) — {ship_points(ship)} pts"]
        if hull is not None:
            for slot in hull.weapon_slots:
                fitted = ship.weapons.get(slot.id, "EMPTY")
                rows.append(f"    [{slot.id}] {slot.name:24s} {slot.size.value:8s} — {fitted}")
        rows.append(f"    upgrades: {', '.join(ship.upgrade_ids) or '(none)'}")
        rows.append(f"    doctrine: {ship.doctrine_id or '(none)'}")
        return "\n".join(rows)

    def _save(self, args: list[str]) -> str:
        from pathlib import Path

        from spacefleet.persistence.fleet_save import default_fleet_dir, save_fleet

        if args:
            path = Path(" ".join(args))
        else:
            safe = self.fleet.name.lower().replace(" ", "_")
            path = default_fleet_dir() / f"{safe}.json"
        try:
            written = save_fleet(self.fleet, path)
        except OSError as exc:
            return f"save failed: {exc}"
        return f"Saved to {written}"

    def _load(self, args: list[str]) -> str:
        from pathlib import Path

        from spacefleet.persistence.fleet_save import load_fleet

        if not args:
            return "usage: load <path>"
        try:
            loaded = load_fleet(Path(" ".join(args)))
        except FleetSpecError as exc:
            return str(exc)
        if loaded.faction is not self.fleet.faction:
            return f"fleet is {loaded.faction.value}, session is {self.fleet.faction.value}"
        backup, self.fleet = self.fleet, loaded
        error = self._revalidate()
        if error:
            self.fleet = backup
            return error
        return f"Loaded '{self.fleet.name}' — {self._status()}"
```

Add `from collections.abc import Callable` to module imports. `_revalidate` in Task 6 already checks budget, so over-budget loads revert via the same path.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fleet_builder_cli.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/cli/fleet_builder_cmd.py tests/test_fleet_builder_cli.py
git commit -m "feat(fleet): equip mode, flagship, save/load in builder session"
```

---

## Task 8: REPL wrapper + app menu wiring

**Files:**
- Modify: `src/spacefleet/cli/fleet_builder_cmd.py`
- Modify: `src/spacefleet/cli/app.py`
- Test: `tests/test_fleet_builder_cli.py` (append — non-interactive parts only)

**Interfaces:**
- Produces: `run_fleet_builder() -> None` (interactive loop; prompts faction + budget via `cli/prompts.py`, then feeds input lines to a session until `done`); app menu `[3] Fleet Builder` dispatches to it.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_run_fleet_builder_is_exported() -> None:
    from spacefleet.cli.fleet_builder_cmd import run_fleet_builder

    assert callable(run_fleet_builder)


def test_app_menu_mentions_fleet_builder() -> None:
    from spacefleet.cli.app import MENU

    assert "Fleet Builder" in MENU
    assert "not yet available" not in MENU
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fleet_builder_cli.py -v`
Expected: FAIL — ImportError / MENU assertion

- [ ] **Step 3: Implement**

`fleet_builder_cmd.py` — append:

```python
def run_fleet_builder() -> None:
    """Interactive fleet-builder loop for the app menu."""
    from spacefleet.cli.colors import C, bold, colored, dim
    from spacefleet.cli.prompts import prompt_int, prompt_with_default

    print(f"\n  {bold('FLEET BUILDER')}\n")
    faction_raw = prompt_with_default("Faction (imperial_navy / chaos_fleet)", "imperial_navy")
    if faction_raw is None:
        return
    try:
        faction = Faction(faction_raw)
    except ValueError:
        print(f"  {colored(f'unknown faction {faction_raw!r}', C.RED)}")
        return
    budget = prompt_int("Points budget", 1000, min_val=1, max_val=100_000)
    if budget is None:
        return
    name = prompt_with_default("Fleet name", "My Fleet")
    if name is None:
        return

    session = FleetBuilderSession(faction, budget=budget, name=name)
    print(dim("  Type 'help' for commands.\n"))
    while not session.done:
        try:
            line = input(f"  [{session.fleet.name} | {session.remaining} pts]> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        output = session.execute(line)
        if output:
            print(output)
```

`app.py`:
- In `MENU`, replace the `[3]` line with: `{colored("[3]", C.BRIGHT_YELLOW)} Fleet Builder`
- In `main()`, replace the `choice == "3"` branch body with:

```python
        elif choice == "3":
            from spacefleet.cli.fleet_builder_cmd import run_fleet_builder

            run_fleet_builder()
```

- Update the fallback hint string if it enumerates options (keep "Please enter 1, 2, 3, or 4.").

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fleet_builder_cli.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q
git add src/spacefleet/cli/fleet_builder_cmd.py src/spacefleet/cli/app.py tests/test_fleet_builder_cli.py
git commit -m "feat(fleet): fleet builder REPL wired into the app menu"
```

---

## Task 9: Integration seal + docs

**Files:**
- Test: `tests/test_custom_fleet_assembly.py` (append)
- Modify: `docs/docs/design/ship-customization.md`

- [ ] **Step 1: Write the integration test** (append)

```python
def test_custom_fleet_full_turn_integration() -> None:
    """Session-built fleet → create_pve_custom → one resolve_turn."""
    from spacefleet.cli.fleet_builder_cmd import FleetBuilderSession
    from spacefleet.net.commands import Command
    from spacefleet.net.turn_resolver import resolve_turn

    s = FleetBuilderSession(Faction.IMPERIAL_NAVY, budget=1000)
    s.execute("buy dauntless_light_cruiser ISS Flag")
    s.execute("equip 1")
    s.execute("slot 1 macro_cannon_3")
    s.execute("upgrade auxiliary_shield_capacitor")
    s.execute("doctrine commissariat")
    s.execute("back")
    s.execute("buy sword_frigate ISS Escort")
    s.execute("done")

    state = GameState.create_pve_custom("paulo", s.fleet, seed=7, num_hulks=2)
    flag = state.ships[state.player_ships["paulo"][0]]
    flag.shields_current = 0  # force regen to be observable

    commands = {
        sid: Command(ship_id=sid, action="pass", args={})
        for sid in state.player_ships["paulo"]
    }
    log = resolve_turn(state, commands)
    assert log is not None
    # Base regen 1 + capacitor 1 = 2 shields back
    assert flag.shields_current == 2
    # Commissariat doctrine wired through assembly
    assert flag.morale_floor == 20
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, zero failures

- [ ] **Step 3: Docs note**

In `docs/docs/design/ship-customization.md`, directly under the `## Fleet Building Interface` heading, add:

```markdown
:::note Implementation status
The fleet builder is implemented: app menu → `[3] Fleet Builder`. Sessions
enforce faction-pure hulls/doctrines, weapon slot rules, upgrade slot caps
(incl. Mechanicus +1), flagship-only upgrades, and a hard points budget
(default 1000). Fleets save as JSON under `data/fleets/` and battle via
`GameState.create_pve_custom`. Cruisers have 3 upgrade slots (the "2-3"
range resolved upward).
:::
```

- [ ] **Step 4: Final gate**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest -q`
Expected: all clean

- [ ] **Step 5: Commit**

```bash
git add tests/test_custom_fleet_assembly.py docs/docs/design/ship-customization.md
git commit -m "test(fleet): session-to-battle integration + docs status note"
```

---

## Self-Review (done at planning time)

- **Spec coverage:** spec layer (T1–T3), persistence (T4), assembly + flagship override + `create_pve_custom` (T5), CLI session (T6–T7), REPL + menu (T8), integration + docs (T9). The `validate_upgrades` seam closes in T2 (spec validation) and T5 (assembly validates before building).
- **Type consistency:** `ShipSpec.weapons: dict[int, str]` everywhere; `FleetSpecError(ValueError)`; `validate_ship_spec(spec, faction, *, is_flagship)`; `ship_points` name consistent across CLI and tests.
- **Known risks flagged in-task:** iconoclast slot/lance compatibility (T2 pre-check note), hull_registry `_load` internals (T3 says read first), import cycles in game_state (T5 note), `_mutate` lambda closures (T7 — snapshot/revert is whole-ship, safe).
