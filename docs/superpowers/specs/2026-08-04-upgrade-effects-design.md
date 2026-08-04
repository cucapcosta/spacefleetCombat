# Upgrade Effects — Design Spec

**Date:** 2026-08-04
**Status:** Approved
**Sub-project:** 3 of 5 (AI ✓ → Doctrine system ✓ → **Upgrade effects** → Fleet builder → Campaign gauntlet)

## Goal

Make ship **upgrades** — the 20 passive enhancements in `data/upgrades/upgrades.yaml`
— actually work in battle and at build time. Today the catalog loads
(`UpgradeRegistry`) but nothing consumes it. After this sub-project, a ship built
with upgrades visibly plays differently, and build-time slot validation exists
(consuming the deferred Mechanicus `upgrade_slot_bonus` from the doctrine
sub-project). This is the second of the three sub-projects the fleet builder
depends on.

Upgrades are **per-ship**, faction-agnostic, occupy limited slots by ship class,
and carry a points cost (used by the fleet builder later). They cannot change
mid-battle.

## Design principle: data-driven effect keys

Unlike doctrines (8 fixed ids → typed `DoctrineDef` fields), upgrades already
declare their behaviour as an **effect dict** in yaml (`effect: {shields: +1}`).
The effects module interprets *effect keys*, not upgrade ids — adding a new
upgrade with existing keys requires only yaml. Helpers:

```python
def upgrade_effect_total(upgrade_ids: list[str], key: str) -> int | float
    # sum of a numeric effect key across the ship's upgrades (0 if none)
def upgrade_has_effect(upgrade_ids: list[str], key: str) -> bool
    # any upgrade declares this (truthy) key
```

Unknown ids inside these helpers are skipped silently (validation catches them
at build time).

## The 20 upgrades and how each lands

### Build-time hull stat mods (`apply_upgrades_to_hull`, `dataclasses.replace`)

| upgrade | effect key | HullProfile field |
|---|---|---|
| additional_void_shield | `shields: +1` | `shields` |
| reinforced_prow | `armor_prow: +1` | `armor_prow` |
| extra_turrets | `turrets: +2` | `turrets` (inert until torpedoes exist; stat is real) |
| efficient_plasma_thrusters | `speed: +5` | `speed` |
| enhanced_maneuvers | `turn_rate: +15` | `turn_rate` |
| improved_augur_array | `sensor_range: +20` | `sensor_range` (detection already reads `hull.sensor_range` — works immediately) |
| crew_quarters | `morale_max: +15` | `base_morale` (`from_profile` seeds `morale`/`morale_max` from it) |

Clamps: `hull_hits>=1`, `shields>=0`, `speed>=0.0`, `turn_rate>=0.0`,
`turrets>=0`, `sensor_range>=0.0`, `base_morale>=1` (same spirit as
`apply_doctrine_to_hull`).

### Build-time ship state (set by `build_ship_with_upgrades`)

| upgrade | effect key | Ship field |
|---|---|---|
| extended_combustion_tanks | `combustion_max: +25`, `combustion_regen: +5` | `combustion_max`/`combustion` +25; new field `combustion_regen_bonus` |
| veteran_crew | `starting_crew_tier: 2` | `battles_survived = SkillRegistry.get_crew_tier(2).battles_required` (5 in fallback) |
| master_of_signals | `stance_cooldown_reduction: 1` | new field `stance_cooldown_reduction`; `switch_stance` sets `cooldown = max(0, data.switch_cooldown - reduction)` |

### Runtime PassiveBus handlers (`register_upgrade_handlers`, per-ship, mirrors doctrine handlers)

| upgrade | effect key | hook |
|---|---|---|
| turbo_weaponry | `battery_strength: +1` | `BATTERY_FIREPOWER_BONUS` |
| auxiliary_shield_capacitor | `shield_regen: +1` | `END_OF_TURN_SHIELD_REGEN` |
| automated_reload | `torpedo_reload_reduction: 1` | `TORPEDO_RELOAD_REDUCTION` (inert until Sprint-6 torpedoes; registration proves loadability, same as commander passives) |

`PassiveBus.build` gains one call: `register_upgrade_handlers(bus, state)`
(local import, after `register_doctrine_handlers`).

### Direct combat-path wiring (static per-ship properties, doctrine precedent: direct lookup, no bus hook)

| upgrade | effect key | wiring point |
|---|---|---|
| armour_piercing_ammo | `ap_close_range: 1` | `apply_damage_pipeline` gains `armor_delta: int = 0` (effective armor = `max(1, armor + armor_delta)`); `resolve_projectile_impact` passes `armor_delta=-N` when `projectile.distance_traveled <= weapon.range * 0.5` and the attacker has the effect |
| disruption_overcharge | `lance_critical_bonus: 0.25` | `resolve_lance_ray`: per penetrating hit, `dice.chance(0.25)` → `roll_critical_hit` + `apply_critical_hit` (base lance-ray crit chance today is 0; the upgrade grants 25%) |
| belt_armour | `first_crit_ignored: true` | new Ship field `belt_armour_spent`; `apply_critical_hit` ignores the first **subsystem-affecting** crit (`shields_collapse`, `thrusters_damaged`, `weapon_destroyed`, `prow_weapons_destroyed`, `engine_damaged`, `bridge_destroyed`), sets the flag, marks `CriticalResult.ignored_by_belt_armour = True`. Structural crits (`hull_breach`, `fire`, `bulkhead_collapse`, `magazine_detonation`) are not blocked |
| fire_suppression_system | `fire_extinguish_chance: 0.50` | `turn_resolver` end phase, before the leadership check: if fires > 0 and `state.dice.chance(0.50)` → `fires -= 1`, emit `FireSuppressedByUpgradeEvent` |
| navigators_chamber | `micro_warp_charges: +1`, `flagship_only: true` | helper `apply_flagship_upgrade_charges(commander, flagship)` bumps `ability_state["micro_warp_jump"].remaining_charges`; called from `net.game_state._assign_default_commander` |
| power_ram | `ram_damage_multiplier: 1.5` | **inert** — no ramming mechanic exists; catalog entry only, documented in Deferred |

## Build-time validation (`validate_upgrades`)

```python
UPGRADE_SLOT_CAPS = {ESCORT: 1, LIGHT_CRUISER: 2, CRUISER: 3, BATTLECRUISER: 3, BATTLESHIP: 4}

def upgrade_slots_for(hull: HullProfile, doctrine_id: str | None = None) -> int
    # class cap + doctrine.upgrade_slot_bonus (Mechanicus Rites — the deferred consumer lands here)
def validate_upgrades(hull, upgrade_ids, *, doctrine_id=None, is_flagship=False) -> None
    # raises LoadoutError on: unknown id, duplicate id, count > slots, flagship_only on non-flagship
```

Design decision: the docs table says Cruiser "2-3"; we fix Cruiser = 3
(tunable constant). `UpgradeProfile` gains a `flagship_only: bool = False`
field (parsed from the yaml top-level key that exists today but is dropped).

## Units (files)

1. **Modify** `src/spacefleet/data/upgrade_registry.py` — `flagship_only` field + parse.
2. **Modify** `src/spacefleet/models/ship.py` — fields `upgrade_ids`,
   `stance_cooldown_reduction`, `combustion_regen_bonus`, `belt_armour_spent`;
   `from_profile` passthrough for `upgrade_ids`; `switch_stance` cooldown reduction.
3. **Create** `src/spacefleet/commander/upgrade_effects.py` — effect-key helpers,
   slot caps, `upgrade_slots_for`, `validate_upgrades`, `apply_upgrades_to_hull`,
   `build_ship_with_upgrades`, `register_upgrade_handlers`,
   `apply_flagship_upgrade_charges`, `FireSuppressedByUpgradeEvent`,
   `ap_armor_delta`, `lance_crit_chance`, `fire_extinguish_chance` accessors.
4. **Modify** `src/spacefleet/commander/passive_skills.py` — call
   `register_upgrade_handlers` from `PassiveBus.build`.
5. **Modify** `src/spacefleet/combat/damage.py` — `armor_delta` param.
6. **Modify** `src/spacefleet/combat/projectile_resolution.py` — AP close-range
   armor delta; lance-ray crit chance.
7. **Modify** `src/spacefleet/combat/critical_hits.py` —
   `CriticalResult.ignored_by_belt_armour`; belt-armour gate in `apply_critical_hit`.
8. **Modify** `src/spacefleet/net/turn_resolver.py` — fire suppression;
   `regenerate_combustion(15 + ship.combustion_regen_bonus)`.
9. **Modify** `src/spacefleet/net/game_state.py` — call
   `apply_flagship_upgrade_charges` in `_assign_default_commander`.
10. **Tests** — `tests/test_upgrade_registry_flagship.py`,
    `tests/test_upgrade_validation.py`, `tests/test_upgrade_effects.py`,
    `tests/test_upgrade_combat.py`, `tests/test_upgrade_battle.py`.

## Non-goals / Deferred

- **`build_ship_with_upgrades` does not self-validate** (final-review finding): the fleet
  builder (sub-project 4) MUST call `validate_upgrades` at loadout time — otherwise slot
  caps and flagship-only enforcement never fire in practice. `validate_upgrades` currently
  has zero call sites in `src/`.
- Belt armour also absorbs boarding-targeted subsystem crits (Lightning Strike) and skips
  the crit's −5 morale when absorbing — accepted, undocumented-in-rules interactions.

- **power_ram** — inert until a ramming mechanic exists (none planned before Sprint 9 polish).
- **extra_turrets / automated_reload** — stat/hook land now; consumed when Sprint-6 torpedoes arrive.
- Upgrade points cost enforcement — fleet builder (sub-project 4). `Loadout.total_cost` unchanged.
- CLI/fleet-builder UX for choosing upgrades — sub-project 4.
- The legacy `combat/resolution.py` battery/lance path (CLI tech demo) — upgrades wire into the
  authoritative net path (`projectile_resolution` + `turn_resolver`) only, same as commander passives.

## Acceptance

`uv run ruff check src tests && uv run ruff format --check src tests &&
uv run mypy --strict src && uv run pytest -q`. All pre-existing tests stay
green; every new Ship field defaults to no-op so nothing regresses.
