# Fleet Builder — Design Spec

**Date:** 2026-08-04
**Status:** Approved
**Sub-project:** 4 of 5 (AI ✓ → Doctrine system ✓ → Upgrade effects ✓ → **Fleet builder** → Campaign gauntlet)

## Goal

Let a player assemble a custom fleet within a points budget — buy hulls, equip
weapons into slots, install upgrades, pick a doctrine, designate a flagship —
then save it and fight it. Produces the fleet-construction layer the campaign
gauntlet (5/5) consumes, and finally gives `validate_upgrades` its call sites
(the deferred seam from the upgrade-effects sub-project).

The CLI grammar follows `docs/docs/design/ship-customization.md` ("Fleet
Building Interface"). Points formula (same doc):

```
ship_points = hull_cost + sum(weapon_costs) + sum(upgrade_costs) + doctrine_cost
```

## Architecture — four layers

### 1. Spec model — `src/spacefleet/models/fleet_spec.py` (new)

Pure serializable description of a fleet; no runtime state.

```python
@dataclass
class ShipSpec:
    name: str
    hull_id: str
    weapons: dict[int, str] = {}        # slot_id -> weapon_id
    upgrade_ids: list[str] = []
    doctrine_id: str | None = None

@dataclass
class FleetSpec:
    name: str
    faction: Faction
    ships: list[ShipSpec] = []
    flagship_index: int = 0

class FleetSpecError(ValueError): ...

def ship_points(spec: ShipSpec) -> int          # raises FleetSpecError on unknown ids
def fleet_points(fleet: FleetSpec) -> int
def validate_ship_spec(spec, faction, *, is_flagship=False) -> None
def validate_fleet_spec(fleet, *, budget: int | None = None) -> None
def fleet_to_dict(fleet) -> dict / fleet_from_dict(d) -> FleetSpec
def apply_default_loadout(spec: ShipSpec) -> None   # from hull yaml default_loadout
```

Validation reuses what exists — no duplicated rules:
- **Weapons**: build `WeaponMount`s from the hull's `weapon_slots` and run
  `Loadout(weapons=...).validate(hull)` (slot exists, type allowed, size fits).
- **Doctrine**: exists; `doctrine.faction == fleet faction`; every equipped
  weapon passes `doctrine_allows_weapon` (Khorne lance ban).
- **Upgrades**: `validate_upgrades(hull, upgrade_ids, doctrine_id=..., is_flagship=...)`
  (slot caps + Mechanicus bonus + flagship-only) — **the seam closes here**.
- **Hull**: exists; `hull.faction == fleet faction` (fleets are faction-pure).
- **Fleet**: ≥1 ship, valid `flagship_index`, unique ship names, and
  `fleet_points <= budget` when a budget is given.

### 2. Persistence — `src/spacefleet/persistence/fleet_save.py` (new)

JSON (stdlib — user saves shouldn't depend on PyYAML): `save_fleet(fleet, path)`,
`load_fleet(path) -> FleetSpec` (raises `FleetSpecError` on bad/missing file).
Default save dir: `get_data_dir()/fleets/` when available, else CWD `fleets/`
(`default_fleet_dir() -> Path`). JSON round-trips `weapons` slot keys via
`fleet_from_dict` int-coercion.

### 3. Battle assembly — `src/spacefleet/net/game_state.py` (modified)

```python
def add_custom_fleet(state, player_id, fleet: FleetSpec, *, start_x=0.0, start_y=0.0, heading=0.0) -> list[str]
```
Validates the spec, then per ship: mounts from hull slot defs + `WeaponRegistry`,
ship via `build_ship_with_upgrades` (doctrine + upgrades all wired), column
formation, registers in `state.ships`/`player_ships`/`kills`, then assigns a
commander with **the spec's flagship** — `_assign_default_commander` gains an
optional `flagship_override: str | None = None` param (default preserves current
behavior). `apply_flagship_upgrade_charges` then hits the right ship for free.

```python
GameState.create_pve_custom(player_id, fleet, *, seed=None, num_hulks=4)
```
Custom fleet vs the existing AI hulks — the first playable consumer.

### 4. CLI — `src/spacefleet/cli/fleet_builder_cmd.py` (new) + `cli/app.py` menu

`FleetBuilderSession(faction, budget=1000, name="My Fleet")` — a **testable
command interpreter**: `execute(line: str) -> str` returns display text, no
input()/print() inside, `done: bool` flag. Two modes:

- **Top level**: `help`, `hulls`, `weapons`, `upgrades`, `doctrines`,
  `buy <hull_id> <name...>`, `remove <n>`, `equip <n>`, `status`,
  `save [path]`, `load <path>`, `done`.
- **Equip mode** (after `equip <n>`): `show`, `slot <n> <weapon_id>`,
  `unslot <n>`, `upgrade <id>`, `remove-upgrade <id>`, `doctrine <id|none>`,
  `flagship`, `default` (hull's yaml `default_loadout`), `back`.

Every mutation is transactional: apply → `validate_ship_spec` + budget check →
on failure revert and return the error text. Budget is a hard cap.

`run_fleet_builder()` wraps the session in an input loop (faction + budget
prompts via `cli/prompts.py`). `cli/app.py` menu slot `[3]` ("Configuration",
currently dead) becomes `[3] Fleet Builder`.

### Supporting change — `HullRegistry.default_loadout(hull_id) -> dict`

Hull yamls already carry `default_loadout` (weapons per slot, upgrades,
doctrine) but the registry drops it. Store raw dicts in a parallel
`_default_loadouts` class map at parse time (avoids touching the frozen,
possibly-hashed `HullProfile`); `reset()` clears it.

## Decisions

- Torpedo weapons are equippable (slots allow them); they fire as generic
  salvos until Sprint-6 torpedo mechanics land. Not the builder's concern.
- Points budget default: **1000** (design-doc example).
- Default flagship: first ship (`flagship_index=0`); `flagship` command reassigns.
- `FleetSpecError` subclasses `ValueError`, mirroring `LoadoutError`; weapon
  slot violations propagate as `LoadoutError` (same family).

## Non-goals / Deferred

- Connecting a saved fleet to the **live server/ws flow** (server-side fleet
  upload) — campaign gauntlet decides how battles start; `create_pve_custom`
  is the hook.
- Ramming/Nova Cannon mechanics, upkeep costs, `commander_level_required`
  gating (yaml fields exist; campaign layer's concern).
- Fleet editing of a *loaded* save beyond what the session commands offer.

## Acceptance

`uv run ruff check src tests && uv run ruff format --check src tests &&
uv run mypy --strict src && uv run pytest -q`. All pre-existing tests stay
green. Integration seal: build a two-ship fleet spec programmatically,
`create_pve_custom`, run one `resolve_turn` — upgrades/doctrine demonstrably
applied (e.g. shield capacitor regen, doctrine morale floor).
