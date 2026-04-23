# Sprint 5 — Commander System Design

**Status:** approved design, ready for implementation plan
**Roadmap:** `docs/docs/architecture/implementation-roadmap.md` → Sprint 5
**Deliverable:** commander abilities usable from flagship, passive skills affect fleet, XP awarded after battle, per-ship crew veterancy.

---

## 1. Goal

Add a commander layer that rides on top of the Sprint 1–4 battle engine:

- A per-fleet `Commander` entity owns active abilities (cooldown/charge-gated, resolved from declarative effect-step primitives) and passive skills (auto-applied via a named-hook dispatcher).
- Every `Ship` tracks `battles_survived`, derives a `crew_tier` from the yaml tier table, and the tier contributes stat bonuses through the same passive hook dispatcher.
- A new **command sub-phase** runs at the start of every turn, before fire. Command → Fire → Movement → End-of-turn.
- XP and crew veterancy are awarded automatically when `state.is_game_over()` becomes true, emitting `XpGainedEvent`, `LevelUpEvent`, `CrewTierUpEvent`.
- Every scenario factory (`create_pve`, `create_pvp`, `create_mixed`) auto-assigns a level-1 commander with a fixed starter loadout to each fleet, and designates the heaviest capital as flagship. Abilities are usable end-to-end with no extra wiring.

Sprint 6-dependent abilities (`torpedo_barrage`, `augur_probe`) and passives (`short_burn_torpedoes`, `reload_drills`, `fleet_torpedo_reload_reduction`, `fleet_torpedo_strength`) are loaded into the registry, exposed as commands, but resolve as no-op stubs that emit `PendingSprint6Event`. Charges/cooldown consume as if resolved. No runtime errors.

---

## 2. Non-goals

- Trait-earning logic. `traits.yaml` is loaded into the registry, and commanders may carry traits, but automatic trait acquisition is a Sprint 9 (narrative) concern.
- Fleet builder CLI. Commanders come from fixed starter loadouts. Loadout customisation is Sprint 6.
- Campaign/persistence. XP + crew veterancy live on in-memory objects; save/load is Sprint 8/9.
- Torpedo and detection integration for the two Sprint 6-dependent abilities.
- Replacing `player_ships: dict[str, list[str]]` on `net.GameState`. The existing mapping stays as the authoritative player→ship linkage for the turn resolver and renderer. `state.fleets: dict[str, Fleet]` is added alongside, keyed on the same ids, and shares the ship ids. Migration to a Fleet-only model is deferred.

---

## 3. Architecture overview

Six new modules and seven modified files.

**New:**

- `src/spacefleet/commander/commander.py` — `Commander`, `AbilityState`, `ActiveBuff` dataclasses
- `src/spacefleet/commander/abilities.py` — effect-step primitives (tagged union), `AbilityDef`, `resolve_ability`
- `src/spacefleet/commander/passive_skills.py` — `PassiveHook` enum, `PassiveContext`, `PassiveBus` dispatcher, handler table
- `src/spacefleet/commander/progression.py` — `LevelDef`, `CrewTierDef`, `apply_xp`, `compute_battle_xp`, `bump_crew_veterancy`, `crew_tier_for`
- `src/spacefleet/data/skill_registry.py` — loads `data/commanders/{skills,traits,level_table}.yaml`, yaml-first with hard-coded fallback
- `src/spacefleet/phases/command_phase.py` — `AbilityOrder`, `resolve_command_phase`

**Modified:**

- `src/spacefleet/models/fleet.py` — adds `commander: Commander | None`, `flagship_ship_id: str | None`, `ship_ids: list[str]`; existing `ships: list[Ship]` field is kept for back-compat with `Fleet.total_hull_points()`; new accessors `ships_in(state)`, `alive_ships_in(state)`, `flagship_in(state)` are the preferred lookup path for new code
- `src/spacefleet/models/ship.py` — adds `battles_survived: int` field; `crew_tier` derived via `progression.crew_tier_for`; crew-tier effects applied via `PassiveBus` (Ship does not hardcode tier effects)
- `src/spacefleet/core/game_state.py` — adds `fleets: dict[str, Fleet]`; new `fleet_of(ship) -> Fleet | None` helper
- `src/spacefleet/net/game_state.py` — auto-populates `fleets` in `create_pve/pvp/mixed`; assigns commander + flagship per fleet
- `src/spacefleet/net/turn_resolver.py` — signature gains `ability_orders`; new command sub-phase runs first; `PassiveBus` built once per turn and referenced at the hook points below
- `src/spacefleet/net/commands.py` — adds `AbilityOrder` dataclass (separate from `Command`)
- `src/spacefleet/cli/game_cmd.py` — new `ability <id> [target_or_x y]` command surface; translates to an `AbilityOrder`

---

## 4. Data model

### 4.1 `Commander`

```python
@dataclass
class AbilityState:
    remaining_charges: int
    cooldown_remaining: int = 0
    preparation_turns_left: int = 0
    pending_order: AbilityOrder | None = None

@dataclass
class ActiveBuff:
    """A timed effect originating from an ability resolution."""
    id: str                       # e.g. "concentrated_fire", "mark_of_chaos"
    source_ability_id: str
    turns_remaining: int
    data: dict[str, Any] = field(default_factory=dict)
    # concentrated_fire: {target_ship_id, column_shift, range_gu}
    # mark_of_chaos:    {lance_strength_bonus, morale_immunity}

@dataclass
class Commander:
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

### 4.2 `Fleet` (extended)

```python
@dataclass
class Fleet:
    id: str = ""                                   # matches player_id or "ai_<n>"
    commander: Commander | None = None
    flagship_ship_id: str | None = None
    ship_ids: list[str] = field(default_factory=list)
    # legacy field kept only for backward compat of one caller (test_fleet_total_hull.py):
    commander_name: str = ""

    def ships_in(self, state: CoreGameState) -> list[Ship]:
        return [state.ships[sid] for sid in self.ship_ids if sid in state.ships]

    def alive_ships_in(self, state: CoreGameState) -> list[Ship]:
        return [s for s in self.ships_in(state) if s.alive]

    def flagship_in(self, state: CoreGameState) -> Ship | None:
        if self.flagship_ship_id is None:
            return None
        ship = state.ships.get(self.flagship_ship_id)
        return ship if (ship is not None and ship.alive) else None
```

`Fleet.ships: list[Ship]` (the current field) becomes a stored list of `Ship` references populated at battle start for back-compat with `Fleet.total_hull_points()`. New code should prefer `ships_in(state)`.

### 4.3 `Ship` additions

```python
battles_survived: int = 0

@property
def crew_tier(self) -> int:
    return crew_tier_for(self.battles_survived)
```

Crew-tier effects (morale_bonus, accuracy_bonus, cooldown_reduction, firepower_bonus) are **not** added as new `effective_*` properties. They register as handlers on `PassiveBus` hooks (ACCURACY_COLUMN_SHIFT, ABILITY_COOLDOWN_REDUCTION, MORALE_STARTING_BONUS, BATTERY_FIREPOWER_BONUS), applied uniformly alongside commander passives.

### 4.4 Effect steps (ability primitives)

Tagged union in `commander/abilities.py`:

```python
@dataclass
class HullRepair:           amount_dice: str  # "D3" | "D6"
@dataclass
class ExtinguishFires:      pass
@dataclass
class RepairTempCritical:   count: int
@dataclass
class AreaMoraleRestore:    range_gu: float; amount: int; cancel_mutiny: bool
@dataclass
class AreaHullDamage:       range_gu: float; amount_dice: str; affects_allies: bool
@dataclass
class AreaMoraleDamage:     range_gu: float; amount: int; affects_allies: bool
@dataclass
class SpawnProbe:           radius: float; duration: int; detection_level: int  # Sprint 6 stub
@dataclass
class ConcentratedFireBuff: range_gu: float; column_shift: int; duration: int
@dataclass
class TimedFleetBuff:       buff_id: str; duration: int; data: dict[str, Any]
@dataclass
class BonusTorpedoSalvo:    range_gu: float                                      # Sprint 6 stub
@dataclass
class Teleport:             # reads target_position from order
@dataclass
class BonusBoardingAssault: actions: int; extended_range_gu: float

EffectStep = (
    HullRepair | ExtinguishFires | RepairTempCritical | AreaMoraleRestore |
    AreaHullDamage | AreaMoraleDamage | SpawnProbe | ConcentratedFireBuff |
    TimedFleetBuff | BonusTorpedoSalvo | Teleport | BonusBoardingAssault
)

@dataclass
class AbilityDef:
    id: str
    name: str
    category: str                       # "universal" | "imperial_navy" | "chaos_fleet"
    cooldown: int
    charges: int
    preparation_turns: int = 0
    range_gu: float | None = None
    faction: Faction | None = None
    sprint6_dependency: bool = False
    steps: list[EffectStep] = field(default_factory=list)
```

### 4.5 `AbilityOrder`

```python
@dataclass
class AbilityOrder:
    fleet_id: str
    ability_id: str
    target_ship_id: str | None = None
    target_position: Vector2D | None = None
```

Lives in `net/commands.py`. Separate from `Command` — rides a separate channel to `resolve_turn`.

### 4.6 Passive hooks

```python
class PassiveHook(StrEnum):
    # stat modifiers (aggregated: sum of contributions)
    FLEET_SPEED_MAX           = "fleet_speed_max"             # +float
    FLEET_SENSOR_RANGE        = "fleet_sensor_range"          # +float
    FLEET_ARMOR_PROW          = "fleet_armor_prow"            # +int
    BATTERY_FIREPOWER_BONUS   = "battery_firepower_bonus"     # +int (master_gunner, crew_tier elite)
    AHEAD_FULL_DICE           = "ahead_full_dice"             # replaces count (first writer wins)
    # hit-time modifiers
    HIT_COLUMN_SHIFT          = "hit_column_shift"            # +int (concentrated_fire, crew_tier accuracy)
    LANCE_HIT_THRESHOLD       = "lance_hit_threshold"         # overrides default (4+ → 3+ for lance_mastery)
    # end-of-turn regen
    END_OF_TURN_SHIELD_REGEN  = "end_of_turn_shield_regen"    # +int
    END_OF_TURN_HULL_REGEN    = "end_of_turn_hull_regen"      # +int, conditional on crippled
    # morale
    MORALE_LOSS_APPLY         = "morale_loss_apply"           # modifies incoming delta (veteran_crews *0.75, mark_of_chaos immunity)
    MORALE_STARTING_BONUS     = "morale_starting_bonus"       # applied at battle start (crew_tier)
    # rule overrides
    HULL_BREACH_APPLY         = "hull_breach_apply"           # bool, reinforced_bulkheads nullifies
    ANTI_MUTINY_CHECK         = "anti_mutiny_check"           # ctx.ship, returns bool "suppress mutiny"
    # ability math
    ABILITY_COOLDOWN_REDUCTION = "ability_cooldown_reduction" # applied when setting cooldown_remaining
    # Sprint 6 stubs (accepted but never dispatched yet)
    TORPEDO_SPEED_MULT        = "torpedo_speed_mult"
    TORPEDO_RELOAD_REDUCTION  = "torpedo_reload_reduction"
    TORPEDO_STRENGTH          = "torpedo_strength"
```

`PassiveBus` is built once at the top of every `resolve_turn` and attached as `state.passives`. It iterates:
1. All `commander.passive_skill_ids` across `state.fleets`
2. All `commander.active_buffs` across `state.fleets`
3. Every `ship.crew_tier` for ship-local contributions
4. Every `commander.trait_ids` (carried-but-inert-earning traits still contribute their effects)

Each registered handler is keyed by `(source_id, hook)` → `fn(ctx) -> value`. Handler lookup is O(active_sources × hooks_per_source), fine for the dozen-commanders, few-dozen-ships scale this game targets.

---

## 5. Turn flow

```
resolve_turn(state, commands, ability_orders=None)
│
├─ 0. Tick commander clocks
│    for each Commander in state.fleets:
│      for each ability_id, st in commander.ability_state.items():
│        st.cooldown_remaining = max(0, st.cooldown_remaining - 1)
│        if st.pending_order and st.preparation_turns_left > 0:
│          st.preparation_turns_left -= 1
│      for buff in commander.active_buffs: buff.turns_remaining -= 1
│      drop buffs where turns_remaining <= 0 → BuffExpiredEvent
│
├─ 1. COMMAND SUB-PHASE
│    state.passives = PassiveBus.build(state)        # built once; abilities mutate commander.active_buffs
│    resolve_command_phase(state, ability_orders, dice):
│      iterate sorted(ability_orders by fleet_id):
│        - Validate order (§7). On failure: emit AbilityRejectedEvent; continue.
│        - If AbilityDef.preparation_turns > 0 AND no pending_order yet:
│            stash order on AbilityState; set preparation_turns_left;
│            charges -= 1; cooldown_remaining = 0 (cooldown starts on resolution)
│            emit AbilityPrepStartedEvent; continue.
│        - If pending_order exists and preparation_turns_left == 0:
│            take the stashed order, clear stash, resolve.
│        - Execute AbilityDef.steps via resolve_ability.
│        - cooldown_remaining = def.cooldown adjusted by ABILITY_COOLDOWN_REDUCTION dispatch.
│        - emit AbilityUsedEvent + per-step events.
│      After command phase, state.passives is REBUILT so subsequent sub-phases
      see any new active_buffs created during command resolution.
│
├─ 2. FIRE SUB-PHASE (existing, with hooks)
│    At hit-resolution for each shot:
│      col_shift = aspect_shift + stance_shift +
│                  PassiveBus.dispatch(HIT_COLUMN_SHIFT, ctx{attacker, target, weapon})
│      fp = weapon.strength + PassiveBus.dispatch(BATTERY_FIREPOWER_BONUS, ctx)
│    Lance hit threshold:
│      threshold = PassiveBus.dispatch(LANCE_HIT_THRESHOLD, ctx) or 4
│    Hull Breach critical:
│      if PassiveBus.dispatch(HULL_BREACH_APPLY, ctx) is False: skip extra damage
│
├─ 3. MOVEMENT SUB-PHASE (existing, with hooks)
│    Ship.effective_speed_max:
│      return self.hull.speed * self.crit_speed_modifier +
│             state.passives.dispatch(FLEET_SPEED_MAX, ctx{ship})
│    Ahead-Full dice count:
│      dice_count = state.passives.dispatch(AHEAD_FULL_DICE, ctx) or 2
│
├─ 4. END-OF-TURN SUB-PHASE (existing, with hooks)
│    shield_regen = base + dispatch(END_OF_TURN_SHIELD_REGEN, ctx)
│    if ship.hull_current < ship.hull.hull_hits * 0.5:
│        hull_regen = dispatch(END_OF_TURN_HULL_REGEN, ctx)
│        ship.hull_current = min(ship.hull.hull_hits, ship.hull_current + hull_regen)
│    Mutiny gate:
│      if dispatch(ANTI_MUTINY_CHECK, ctx{ship}) is True:
│        morale clamped at 1 this turn (mutiny suppressed for ships within 40 GU of flagship)
│
└─ 5. GAME-OVER CHECK
     if state.is_game_over():
       winning_faction = sole surviving faction (or None on draw)
       for fleet in state.fleets.values():
         if fleet.commander and fleet.alive_ships_in(state):
           xp = compute_battle_xp_for(fleet, state, winning_faction)
           apply_xp(fleet.commander, xp) → XpGainedEvent, maybe LevelUpEvent(s)
         for ship in fleet.alive_ships_in(state):
           bump_crew_veterancy(ship) → maybe CrewTierUpEvent
```

Morale loss path:

```python
ship.apply_morale_change(delta, state=state)   # state now optional
  if state is not None and delta < 0:
    fleet = state.fleet_of(self)
    modified = state.passives.dispatch(
        PassiveHook.MORALE_LOSS_APPLY,
        PassiveContext(ship=self, fleet=fleet, state=state, value=delta),
    )
    delta = int(modified)
  self.morale = clamp(self.morale + delta, 0, self.morale_max)
```

Every combat call site that currently calls `apply_morale_change` gains a `state=state` kwarg. Tests that call `apply_morale_change` on a standalone ship (no state) continue to pass through the raw delta.

---

## 6. Ability catalogue (all ten)

| Ability | Category | Steps | Sprint 6 dep |
|---|---|---|---|
| `micro_warp_jump` | universal | `Teleport` (gated by preparation_turns=1, interruptible by boarding during prep) | no |
| `emergency_repairs` | universal | `HullRepair("D3")`, `ExtinguishFires`, `RepairTempCritical(1)` | no |
| `call_to_arms` | universal | `AreaMoraleRestore(range=40, amount=30, cancel_mutiny=True)` | no |
| `augur_probe` | universal | `SpawnProbe(radius=30, duration=3, detection_level=3)` | **yes** (no-op stub, emits `PendingSprint6Event`) |
| `concentrated_fire` | universal | `ConcentratedFireBuff(range_gu=30, column_shift=+1, duration=2)` | no |
| `torpedo_barrage` | imperial_navy | `BonusTorpedoSalvo(range_gu=50)` | **yes** (no-op stub) |
| `boarding_assault` | imperial_navy | `BonusBoardingAssault(actions=3, extended_range_gu=15)` | no |
| `warp_rift` | chaos_fleet | `AreaHullDamage(range=15, dice="D3", affects_allies=True)`, `AreaMoraleDamage(range=15, amount=20, affects_allies=True)` | no |
| `mark_of_chaos` | chaos_fleet | `TimedFleetBuff(buff_id="mark_of_chaos", duration=3, data={lance_strength_bonus:+2, morale_immunity:True})` | no |

Faction-gated abilities are rejected with `AbilityRejectedEvent(reason="faction_mismatch")` if the commander's faction does not match.

`warp_rift` hull damage routes through `apply_damage_pipeline` (shields absorb first). Not a shield-bypass.

---

## 7. Validation rules

Applied in `resolve_command_phase` before executing steps. All failures emit `AbilityRejectedEvent(ability_id, reason)` and do NOT consume charges or trigger cooldown.

| Check | Reason string |
|---|---|
| `state.fleets.get(order.fleet_id)` is None | `no_fleet` |
| `fleet.commander` is None | `no_commander` |
| `fleet.flagship_in(state)` is None | `flagship_down` |
| `ability_id not in commander.active_ability_ids` | `not_owned` |
| `AbilityDef.faction not in (None, commander.faction)` | `faction_mismatch` |
| `ability_state.remaining_charges == 0` | `no_charges` |
| `ability_state.cooldown_remaining > 0` | `cooldown` |
| target_ship_id given but ship missing/destroyed | `target_missing` |
| target_position given and ability has `range_gu` and flagship→position > range_gu | `out_of_range` |
| target_ship_id given and ability has `range_gu` and flagship→target > range_gu | `out_of_range` |

**Interruption (micro-warp prep):** during the strike sub-phase (existing), if any boarding action resolves against a flagship whose commander has a pending `micro_warp_jump`, emit `AbilityInterruptedEvent(reason="boarding")`, clear `pending_order`, **restore** charges (prep did not succeed), reset `preparation_turns_left` to 0.

**Running silent:** if flagship is in `RUNNING_SILENT` and ability fires, emit `StanceChangeEvent` (existing silence-broken pattern), then proceed with ability resolution.

---

## 8. Data loading

`src/spacefleet/data/skill_registry.py` follows the `HullRegistry` pattern.

Walks:
- `data/commanders/skills.yaml` → `active_abilities: dict` + `passive_skills: dict`
- `data/commanders/traits.yaml` → `traits: dict`
- `data/commanders/level_table.yaml` → `levels: dict` + `crew_experience_tiers: dict` + `xp_sources: dict`

Parses each entry into `AbilityDef` / `PassiveSkillDef` / `TraitDef` / `LevelDef` / `CrewTierDef`. Yaml `effects:` dicts map onto effect-step constructors via a small parser table (switch on known keys: `hull_restore`, `extinguish_fires`, `morale_restore`, etc.).

Unknown effect keys log a warning and are ignored. Sprint 6-dep abilities are detected by the presence of `bonus_torpedo_salvo`, `probe_radius`, etc. and marked `sprint6_dependency=True`.

**Fallback** (yaml unavailable or empty): hard-coded subset covering `concentrated_fire`, `emergency_repairs`, `call_to_arms`, `veteran_crews`, `master_gunner`, levels 1–3, crew tiers 0–1, minimal xp_sources. Enough to make core tests run without the yaml.

---

## 9. Scenario auto-assignment

Inside `net/game_state.py::_add_imperial_fleet` / `_add_chaos_fleet` / `_add_ai_hulks`, after populating ship lists:

```python
def _assign_default_commander(
    state: GameState,
    fleet_id: str,
    ship_ids: list[str],
    faction: Faction,
) -> None:
    if not ship_ids:
        return
    ships = [state.ships[sid] for sid in ship_ids]
    # pick flagship: heaviest ShipClass (capitals > light cruisers > escorts); ties by id
    # _class_weight is a small local helper mapping ShipClass enum → int ordinal
    # (BATTLESHIP=5, BATTLECRUISER=4, CRUISER=3, LIGHT_CRUISER=2, ESCORT=1)
    flagship = max(ships, key=lambda s: (_class_weight(s.hull.classification), s.id))
    cmdr = _build_starter_commander(fleet_id, faction)
    fleet = Fleet(
        id=fleet_id,
        commander=cmdr,
        flagship_ship_id=flagship.id,
        ship_ids=list(ship_ids),
        commander_name=cmdr.name,
        ships=list(ships),   # legacy field
    )
    state.fleets[fleet_id] = fleet

def _build_starter_commander(fleet_id: str, faction: Faction) -> Commander:
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
        active_ability_ids=active,
        passive_skill_ids=passive,
    )
    for aid in active:
        d = SkillRegistry.get_active(aid)
        cmdr.ability_state[aid] = AbilityState(remaining_charges=d.charges)
    return cmdr
```

Called once per `_add_imperial_fleet`/`_add_chaos_fleet` per player, and once per `_add_ai_hulks` group. AI fleets (hulks) get no commander (`fleet.commander = None`) — hulks are static and abilities no-op.

---

## 10. Progression

`compute_battle_xp(fleet, state, winning_faction) -> int`:

```
xp = 0
if winning_faction == fleet.commander.faction:  xp += xp_sources["battle_victory"]     # 100
elif fleet.alive_ships_in(state):               xp += xp_sources["battle_defeat_survived"]  # 30

kills attributed to this fleet:
  for each SalvoImpactEvent / LanceFireEvent in TurnLog chain where attacker in fleet.ship_ids
  and target_destroyed: classify hull.classification → capital vs escort, accrue
  xp += capitals_killed * xp_sources["enemy_capital_destroyed"]    # 25
  xp += escorts_killed  * xp_sources["enemy_escort_destroyed"]      # 10

first-blood bonus:
  tracked via state.first_blood_awarded_fleet_id (set once per battle on first kill)
  if fleet.id == state.first_blood_awarded_fleet_id: xp += xp_sources["first_blood"]  # 15
```

`objective_completed` and `story_mission_completed` are Sprint 8/9 concerns — xp source known in registry but no trigger in Sprint 5.

Kill attribution already exists on `state.kills: dict[player_id, int]` but is per-player, not per-fleet. For Sprint 5 the mapping is 1:1 (fleet_id == player_id except for AI), so the existing counter is usable directly.

`apply_xp(commander, amount) -> list[Event]`:

```
commander.xp += amount
events = [XpGainedEvent(commander, amount)]
while True:
    nxt = SkillRegistry.get_level(commander.level + 1)
    if nxt is None: break                       # level 10 cap
    if commander.xp < nxt.xp_required: break
    commander.level += 1
    events.append(LevelUpEvent(commander, new_level=commander.level,
                               unlocks=nxt.unlocks, title=nxt.title))
return events
```

`bump_crew_veterancy(ship)`:

```
old_tier = ship.crew_tier
ship.battles_survived += 1
new_tier = ship.crew_tier
if new_tier != old_tier:
    emit CrewTierUpEvent(ship, old_tier, new_tier)
```

`crew_tier_for(battles)` walks the crew_tier table and returns the highest tier whose `battles_required <= battles`.

---

## 11. CLI surface

`cli/game_cmd.py` adds:

```
ability <ability_id> [target_ship_id]
ability <ability_id> at <x> <y>
```

Parser produces an `AbilityOrder` keyed to the player's fleet. A turn's ability orders live on the orchestrator alongside ship commands, passed to `resolve_turn`.

`status` output gains a `Commander:` line per fleet showing level, XP progress, active-ability cooldowns/charges.

---

## 12. Error handling

All order-validation failures emit `AbilityRejectedEvent` and skip (§7). No raises into the resolver.

`SkillRegistry.ensure_loaded` logs a warning and falls back to the hard-coded subset on:
- PyYAML not installed
- yaml file missing
- yaml parse error
- entry missing required key

Effect-step resolvers handle "invalid target" (destroyed between validation and resolution — impossible in the current single-thread model but guarded for safety) by emitting an event and continuing.

`apply_xp` never raises — level 10 is hard cap.

`bump_crew_veterancy` caps crew tier at 4 (highest tier defined). Integer overflow not a concern.

Sprint 6 stubs (`SpawnProbe`, `BonusTorpedoSalvo`) always emit `PendingSprint6Event(ability_id)` and return successfully. Charges + cooldown consume. Documented in the ability's registry entry (`sprint6_dependency=True`).

---

## 13. Testing strategy

TDD per task: failing test → implementation → pass → commit.

**Unit tests** (isolated, no full `GameState`):

- `tests/test_commander_entity.py` — construction, charges default, ability_state init
- `tests/test_ability_state_tick.py` — cooldown/prep decrement, buff expiry
- `tests/test_progression_xp.py` — single level, multi-level overflow, cap at 10
- `tests/test_progression_crew_tier.py` — tier lookup, battles_survived increment, cap at 4
- `tests/test_skill_registry_yaml.py` — yaml load populates all known ids
- `tests/test_skill_registry_fallback.py` — yaml-less path still produces usable registry
- `tests/test_effect_step_hull_repair.py`, `_extinguish_fires.py`, `_area_morale_restore.py`, `_area_hull_damage.py`, `_area_morale_damage.py`, `_concentrated_fire_buff.py`, `_timed_fleet_buff.py`, `_bonus_boarding_assault.py`, `_teleport.py` — one per step
- `tests/test_passive_bus_dispatch.py` — registration, aggregation (sum), override (first writer), handler order

**Integration tests** (with `GameState` + `resolve_turn`):

- `tests/test_command_phase_emergency_repairs.py`
- `tests/test_command_phase_concentrated_fire_column_shift.py` — paint target, next turn fire produces more hits vs baseline
- `tests/test_command_phase_call_to_arms_morale.py` — AoE restore; cancels mutiny
- `tests/test_command_phase_warp_rift_damage_and_morale.py` — AoE damage through pipeline (shields first), morale through hook
- `tests/test_command_phase_mark_of_chaos_morale_immunity.py`
- `tests/test_command_phase_micro_warp_prep_and_resolve.py` — turn 1 stash, turn 2 teleport, interrupt-on-boarding test
- `tests/test_command_phase_cooldown_and_charges.py`
- `tests/test_command_phase_running_silent_breaks.py`
- `tests/test_command_phase_flagship_destroyed_rejects.py`
- `tests/test_command_phase_faction_mismatch_rejects.py`
- `tests/test_passive_veteran_crews_reduces_morale_loss.py`
- `tests/test_passive_swift_maneuvers_speed_bonus.py`
- `tests/test_passive_iron_discipline_anti_mutiny.py`
- `tests/test_passive_shield_harmonics_end_of_turn.py`
- `tests/test_passive_dark_blessings_crippled_regen.py`
- `tests/test_crew_tier_accuracy_bonus.py`
- `tests/test_crew_tier_cooldown_reduction.py`

**End-to-end tests:**

- `tests/test_default_commander_assignment.py` — `create_pve/pvp/mixed` populate fleets + commanders + flagship
- `tests/test_battle_end_awards_xp.py` — `is_game_over` triggers XP + events
- `tests/test_battle_end_bumps_crew_veterancy.py`

**Regression:** all 135 existing tests stay green. The key risk is `apply_morale_change` gaining an optional `state` kwarg — every existing caller must keep working with `state=None` or the new kwarg passed.

**Gate per task:** `pytest -q`, `ruff check src tests`, `ruff format --check src tests`, `mypy --strict src` all green before each commit.

---

## 14. Build sequence (anticipated — implementation plan will lock this)

1. `data/skill_registry.py` + registry types + fallback
2. `commander/commander.py` (entity + buff + ability_state)
3. `commander/progression.py` (XP + crew tier math)
4. `commander/passive_skills.py` (hook enum + dispatcher + handler table for universal passives)
5. `commander/abilities.py` (effect-step primitives + resolver)
6. `phases/command_phase.py` (ticks + validation + dispatch)
7. `core/game_state.py` + `models/fleet.py` + `models/ship.py` modifications
8. `net/commands.py` — `AbilityOrder`
9. `net/turn_resolver.py` — wire command phase, build `PassiveBus`, hook the four sub-phases
10. `net/game_state.py` — auto-assign commanders in scenarios
11. `cli/game_cmd.py` — ability command surface
12. Faction-specific passives + abilities (lance_mastery, mark_of_chaos, warp_rift, prow_of_the_emperor, boarding_assault, speed_of_chaos, dark_blessings, reinforced_bulkheads, sensor_mastery, iron_discipline, shield_harmonics, master_gunner, swift_maneuvers, micro_warp_jump, emergency_repairs, call_to_arms, concentrated_fire)
13. Sprint 6 stubs (`SpawnProbe`, `BonusTorpedoSalvo`, and the four torpedo-related passives)
14. Battle-end XP + crew veterancy wiring

The implementation plan (next step, writing-plans skill) breaks this into granular tasks with tests-first ordering and explicit commit boundaries.
