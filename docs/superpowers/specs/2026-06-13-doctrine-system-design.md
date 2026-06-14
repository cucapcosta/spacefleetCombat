# Doctrine System — Design Spec

**Date:** 2026-06-13
**Status:** Approved
**Sub-project:** 2 of 5 (AI ✓ → **Doctrine system** → Upgrade effects → Fleet builder → Campaign gauntlet)

## Goal

Add per-ship **doctrines** — a faction-specific bonus chosen at ship configuration
— and make all eight doctrine effects actually work in battle and at build time.
A ship's doctrine should visibly change how it plays. This is the first of the
three sub-projects the fleet builder depends on.

Doctrines are **per-ship** (one doctrine slot per ship), faction-locked, and carry
a points cost (used by the fleet builder later). They cannot change mid-battle.

## The eight doctrines (from `docs/docs/design/ship-customization.md`)

| id | name | faction | effect |
|----|------|---------|--------|
| `navy_gunnery_school` | Navy Gunnery School | imperial_navy | batteries on this ship +1 gunnery column shift |
| `commissariat` | Commissariat | imperial_navy | cannot mutiny; morale cannot drop below 20 |
| `space_marine_detachment` | Space Marine Detachment | imperial_navy | +2 boarding assault actions; immune to enemy boarding |
| `mechanicus_rites` | Mechanicus Rites | imperial_navy | +1 upgrade slot on this ship (build-time) |
| `mark_of_khorne` | Mark of Khorne | chaos_fleet | +3 boarding assault actions; cannot equip lances (build-time) |
| `mark_of_tzeentch` | Mark of Tzeentch | chaos_fleet | lance hits on 3+ instead of 4+; −1 hull |
| `mark_of_nurgle` | Mark of Nurgle | chaos_fleet | +2 hull; −5 speed |
| `mark_of_slaanesh` | Mark of Slaanesh | chaos_fleet | +10 speed; −1 shield |

Costs (new, assigned in yaml; tunable): gunnery/commissariat/nurgle/slaanesh = 15;
space_marine/khorne/tzeentch = 25; mechanicus_rites = 20.

## Units (files)

### 1. `data/doctrines/doctrines.yaml` + `src/spacefleet/data/doctrine_registry.py` (new)

`DoctrineDef` (frozen dataclass):

```python
@dataclass(frozen=True)
class DoctrineDef:
    id: str
    name: str
    faction: str            # "imperial_navy" | "chaos_fleet"
    cost: int
    description: str
    # structured effect fields (all default to a no-op value)
    column_shift: int = 0
    lance_threshold: int | None = None     # None = unchanged (4)
    assault_bonus: int = 0
    board_immune: bool = False
    morale_floor: int = 0
    hull_delta: int = 0
    speed_delta: float = 0.0
    shield_delta: int = 0
    lances_allowed: bool = True
    upgrade_slot_bonus: int = 0
```

`DoctrineRegistry` mirrors the existing registries (`WeaponRegistry`/`UpgradeRegistry`):
classmethods `ensure_loaded()`, `all() -> dict[str, DoctrineDef]`, `get(id) -> DoctrineDef`,
`get_or_none(id)`, and `for_faction(faction: Faction) -> list[DoctrineDef]`. Loads
from `data/doctrines/doctrines.yaml` via the shared `load_yaml_file`; falls back to
a hardcoded table of the eight doctrines when yaml is missing (same fallback pattern
as `skill_registry`). Export `DoctrineRegistry` from `spacefleet.data`.

### 2. `Ship` gains two fields (`src/spacefleet/models/ship.py`)

```python
    doctrine_id: str | None = None   # set at construction from the ship's doctrine
    morale_floor: int = 0            # Commissariat sets 20; default 0
```

Both have defaults, so existing `Ship.from_profile(...)` calls and tests are
unaffected. `apply_morale_change` changes its clamp from `max(0, ...)` to
`max(self.morale_floor, min(self.morale_max, ...))`. `from_profile` gains an
optional `doctrine_id: str | None = None` and `morale_floor: int = 0` passthrough.

### 3. `src/spacefleet/commander/doctrine_effects.py` (new)

```python
def apply_doctrine_to_hull(hull: HullProfile, doctrine: DoctrineDef) -> HullProfile:
    """Return a hull copy with the doctrine's build-time stat deltas applied.
    Clamp after applying: hull_hits >= 1, shields >= 0, speed >= 0.0."""

def build_ship_with_doctrine(
    ship_id, name, hull, weapons, *, doctrine_id, position=None, heading=0.0
) -> Ship:
    """Construct a Ship applying a doctrine: stat-modded hull + doctrine_id +
    morale_floor. doctrine_id=None builds a plain ship (no-op)."""

def register_doctrine_handlers(bus: PassiveBus, state: CoreGameState) -> None:
    """Per-ship PassiveBus handlers keyed on ship.doctrine_id:
       column_shift -> HIT_COLUMN_SHIFT, lance_threshold -> LANCE_HIT_THRESHOLD,
       assault_bonus -> ASSAULT_ACTION_BONUS, morale_floor/cannot-mutiny ->
       ANTI_MUTINY_CHECK (returns True so a doctrine ship never mutinies)."""
```

`register_doctrine_handlers` is called from `PassiveBus.build` alongside the
existing `_register_*` helpers.

### 4. New runtime plumbing

- **Assault bonus:** add a public helper `assault_action_bonus(state, ship) -> int`
  in `passive_skills.py` (dispatches `ASSAULT_ACTION_BONUS`, base 0 — the enum and
  registration already exist from Sprint 5 but no consumer helper does). In
  `net/turn_resolver.py` strike sub-phase, change
  `assault_actions = ship.hull.assault_actions` to
  `ship.hull.assault_actions + assault_action_bonus(state, ship)`.
- **Boarding immunity:** in the same strike loop, before resolving boarding, skip
  (and emit a `BoardingRepelledByDoctrineEvent`) when the target ship's doctrine
  has `board_immune` (look up `DoctrineRegistry.get_or_none(target.doctrine_id)`).
- **Morale floor:** handled by the `Ship.morale_floor` clamp above; doctrine sets it
  at build time. Commissariat's "cannot mutiny" is also enforced by an
  `ANTI_MUTINY_CHECK` handler returning `True`.
- **Lance threshold / column shift:** already live hooks in
  `combat/projectile_resolution.py`; the per-ship doctrine handlers feed them.

### 5. Build-time validation rule (defined here, enforced by the builder in #4)

`doctrine_allows_weapon(doctrine, weapon) -> bool` — returns False for a lance when
`lances_allowed` is False (Khorne). `upgrade_slot_bonus` is read by the builder's
upgrade-slot cap. These are pure helpers in `doctrine_effects.py`; the fleet builder
sub-project calls them.

## Determinism

No new randomness. Stat mods and handler registration are pure given state.

## Testing (`tests/test_doctrine_*.py`)

- **registry:** loads 8 doctrines; `for_faction` filters; fallback works without yaml.
- **stat mods:** `apply_doctrine_to_hull` — Nurgle +2 hull/−5 speed, Slaanesh
  +10 speed/−1 shield, Tzeentch −1 hull; a built Nurgle ship has the modified
  `hull.hull_hits`/`speed`.
- **column shift:** a Navy Gunnery ship resolving a battery salvo gets +1 column
  (assert via `hit_column_shift(state, ship, target, weapon) == 1` with the bus built).
- **lance threshold:** a Tzeentch ship → `lance_hit_threshold(state, ship) == 3`.
- **assault bonus:** Space Marine ship → strike resolves with `hull.assault_actions+2`
  actions (assert via `assault_action_bonus(state, ship) == 2` and an integration
  strike that uses the boosted count).
- **boarding immunity:** a boarding strike targeting a Space Marine ship is repelled
  with no crew/subsystem damage; a `BoardingRepelledByDoctrineEvent` is emitted.
- **commissariat:** a ship with Commissariat taking −100 morale stays at ≥ 20 and
  `anti_mutiny_suppressed`/never-mutiny holds; shields keep regenerating.
- **khorne lance ban:** `doctrine_allows_weapon(khorne, lance_weapon) is False`,
  `(khorne, battery)` is True.

## Quality gate

`uv run ruff check src tests && uv run ruff format --check src tests &&
uv run mypy --strict src && uv run pytest -q`. All pre-existing tests (currently
246) stay green; the two new `Ship` fields default to no-op so nothing regresses.

## Deferred

Mechanicus's `upgrade_slot_bonus` only has meaning once the upgrade-slot cap exists
(sub-project 3 / 4) — the field + helper land here; the cap that consumes it lands
with upgrades/builder.
