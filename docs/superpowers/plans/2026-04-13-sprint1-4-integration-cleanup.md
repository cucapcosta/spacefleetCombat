# Sprint 1-4 Integration Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the modules added by `2026-04-13-sprint1-4-gap-fill.md` into the runtime so they actually do work, eliminating the 8 "exists but nothing calls it" findings from the post-gap-fill code review.

**Architecture:** Each task either makes an existing model own a previously-extracted dataclass (Subsystems, StanceState) via property forwarders, or routes a legacy call site through a previously-extracted helper (morale_effects, damage pipeline, CoreGameState inheritance, movement_phase resolver, EventBus publishers). No new public surface is added — every change is a swap from inline implementation to the canonical helper. The only behavioural change is to the combustion economy: combustion is now an **over-burn fuel** spent only when pushing a ship above its `effective_speed_max`. Speeds inside the normal range are free; deceleration is always free.

**Tech Stack:** Python 3.12, dataclasses with `field(default_factory=...)`, pytest, ruff, mypy `--strict`. No new dependencies.

---

## Out of scope

- **`phases/shooting_phase.py` wiring into `net/turn_resolver.py`.** The phase resolver assumes instant resolution (calls `resolve_attack` directly), while `turn_resolver` distinguishes lance (instant ray-cast) from battery (creates a `Projectile` salvo that resolves on impact). Unifying the two requires either teaching `shooting_phase` about projectile launch semantics or rewriting `turn_resolver`'s firing model — both bigger than this plan. Leave `shooting_phase.py` as forward-only infra for future single-player CLI battles.
- **Sprint 5+ work.** This plan only addresses the open items inside the "done" sprints (1-4).

---

## Conventions every task follows

- All edits stay on a single feature branch off `main`.
- TDD: failing test → run → impl → run → commit. Every task ends with `pytest -q`, `ruff check src tests`, `ruff format --check src tests`, `mypy --strict src` all green before commit.
- Commits use Conventional Commits (`feat:`, `refactor:`, `fix:`).
- HEREDOC commit messages with the trailer:

```
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

- All commands run from the worktree root with `uv run`.

---

## File map

**Modify:**
- `src/spacefleet/models/ship.py` — combustion-aware `set_speed`; `Subsystems`/`StanceState` field migration with property forwarders; `switch_stance` uses `can_switch`.
- `src/spacefleet/combat/resolution.py` — call `apply_damage_pipeline`; call `apply_hull_damage_morale`/`apply_critical_hit_morale`.
- `src/spacefleet/combat/projectile_resolution.py` — same morale + damage refactor.
- `src/spacefleet/combat/boarding.py` — call `apply_boarding_crew_morale`.
- `src/spacefleet/combat/critical_hits.py` — call `apply_critical_hit_morale`.
- `src/spacefleet/combat/damage.py` — extend `DamageReport` with `details: list[HitDetail]`; move `HitDetail` here.
- `src/spacefleet/core/game_state.py` — rename `enemies_of`/`friendlies_of` to `enemy_ships_of`/`friendly_ships_of`; add optional `events: EventBus` field.
- `src/spacefleet/net/game_state.py` — make `GameState(CoreGameState)`; drop duplicated fields/methods.
- `src/spacefleet/net/turn_resolver.py` — call `resolve_movement_phase`; publish events on `state.events`.
- `tests/test_core_game_state.py` — match renamed methods.

**Create:**
- `tests/test_set_speed_combustion.py`
- `tests/test_ship_subsystems_migration.py`
- `tests/test_ship_stance_migration.py`
- `tests/test_morale_effects_wiring.py`
- `tests/test_damage_details.py`
- `tests/test_game_state_inheritance.py`
- `tests/test_turn_resolver_movement_phase.py`
- `tests/test_event_publish.py`

---

# Task 1: Combustion as over-burn fuel

**Files:**
- Modify: `src/spacefleet/spatial/movement.py` — new combustion model
- Modify: `src/spacefleet/models/ship.py:299-301` — `set_speed` uses it
- Modify: `src/spacefleet/phases/movement_phase.py` — drop `accelerate`/`decelerate` imports
- Modify: `tests/test_movement.py` — rewrite for new model
- Modify: `tests/test_movement_phase.py:37-38` — combustion no longer drops on normal ahead
- Test: `tests/test_set_speed_combustion.py`

**New semantics:** Combustion is afterburner fuel, not per-acceleration tax.

- Speed ∈ `[0, effective_speed_max]` — **free** (no combustion spent, no raise).
- Speed ∈ `(effective_speed_max, effective_speed_max + current_combustion]` — **over-burn**, costs 1 combustion per 1 GU above `effective_speed_max`.
- Deceleration (in any range) — free.
- If requested target exceeds what combustion can pay for, the speed clamps to `effective_speed_max + available_combustion`.

This replaces the previous "every GU of acceleration costs 1 combustion" model written into Task 1 of the earlier gap-fill plan. The old `spatial.movement.accelerate`/`decelerate`/`CombustionError` helpers go away — `Ship.set_speed` becomes the single API and phase resolvers call it directly.

- [ ] **Step 1: Write failing test**

`tests/test_set_speed_combustion.py`:
```python
"""Ship.set_speed — over-burn combustion model."""
from __future__ import annotations

import pytest

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_within_max_is_free() -> None:
    ship = _ship()
    ship.combustion = 50
    cap = ship.effective_speed_max
    ship.set_speed(cap)
    assert ship.speed == cap
    assert ship.combustion == 50


def test_exactly_at_max_is_free() -> None:
    ship = _ship()
    ship.combustion = 50
    ship.set_speed(ship.effective_speed_max)
    assert ship.combustion == 50


def test_over_burn_spends_combustion() -> None:
    ship = _ship()
    ship.combustion = 10
    cap = ship.effective_speed_max
    ship.set_speed(cap + 5)
    assert ship.speed == cap + 5
    assert ship.combustion == 5


def test_over_burn_clamps_to_available_combustion() -> None:
    ship = _ship()
    ship.combustion = 3
    cap = ship.effective_speed_max
    ship.set_speed(cap + 10)
    # Only 3 combustion → speed rises 3 GU above cap
    assert ship.speed == cap + 3
    assert ship.combustion == 0


def test_decelerate_from_over_burn_is_free() -> None:
    ship = _ship()
    ship.combustion = 0
    cap = ship.effective_speed_max
    ship.speed = cap + 5
    ship.set_speed(cap)
    assert ship.speed == cap
    assert ship.combustion == 0


def test_decelerate_within_normal_range_is_free() -> None:
    ship = _ship()
    ship.combustion = 10
    ship.speed = 15.0
    ship.set_speed(5.0)
    assert ship.speed == 5.0
    assert ship.combustion == 10


def test_raising_further_while_already_over_burn_costs_delta_only() -> None:
    ship = _ship()
    ship.combustion = 10
    cap = ship.effective_speed_max
    ship.speed = cap + 2  # already 2 GU over
    ship.set_speed(cap + 5)  # raise by 3 more
    assert ship.speed == cap + 5
    assert ship.combustion == 7  # only 3 spent


def test_negative_target_clamps_to_zero() -> None:
    ship = _ship()
    ship.speed = 10.0
    ship.set_speed(-5.0)
    assert ship.speed == 0.0
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_set_speed_combustion.py -v`
Expected: `test_over_burn_spends_combustion` and friends FAIL — current `Ship.set_speed` clamps to `effective_speed_max`, silently refusing to go above it.

- [ ] **Step 3: Rewrite `spatial/movement.py`**

Replace `src/spacefleet/spatial/movement.py` entirely:

```python
"""Combustion economy for over-burn movement.

Combustion is afterburner fuel — it is **only** spent when a ship
accelerates above its ``effective_speed_max``.  Normal speed changes
inside ``[0, effective_speed_max]`` and any deceleration are free.

``Ship.set_speed`` is the single public API; this module only exposes
the pure helpers it needs.
"""

from __future__ import annotations

import math


def combustion_cost(
    *,
    current_speed: float,
    target_speed: float,
    max_speed: float,
) -> int:
    """Combustion cost of moving from *current_speed* to *target_speed*.

    Only the portion **above** *max_speed* costs combustion.  The cost is
    ``ceil(target_over − current_over)`` where ``*_over`` is
    ``max(0, speed − max_speed)``.  Returns 0 for any change that stays
    within the normal range or that decreases the over-burn portion.
    """
    current_over = max(0.0, current_speed - max_speed)
    target_over = max(0.0, target_speed - max_speed)
    additional = target_over - current_over
    if additional <= 0:
        return 0
    return math.ceil(additional)
```

No `CombustionError`, no `accelerate`, no `decelerate`. Delete them.

- [ ] **Step 4: Rewrite `Ship.set_speed`**

Replace `src/spacefleet/models/ship.py:299-301`:

```python
    def set_speed(self, target: float) -> None:
        """Change speed, spending combustion only for over-burn.

        Speed inside ``[0, effective_speed_max]`` is free.  Raising the
        speed *above* ``effective_speed_max`` costs 1 combustion per
        1 GU of over-burn (rounded up).  If combustion runs out, the
        target is clamped to ``effective_speed_max + available`` rather
        than raising.  Deceleration is always free.
        """
        from spacefleet.spatial.movement import combustion_cost

        target = max(0.0, target)
        cap = self.effective_speed_max
        cost = combustion_cost(
            current_speed=self.speed,
            target_speed=target,
            max_speed=cap,
        )
        if cost == 0:
            # Free zone (within normal range, or decelerating the over-burn)
            self.speed = target
            return
        affordable = min(cost, self.combustion)
        self.combustion -= affordable
        current_over = max(0.0, self.speed - cap)
        self.speed = cap + current_over + affordable
```

- [ ] **Step 5: Update `phases/movement_phase.py` to use `ship.set_speed` directly**

In `src/spacefleet/phases/movement_phase.py`, replace the import block:

```python
from spacefleet.spatial.movement import CombustionError, accelerate, decelerate
```

with nothing — the helpers are gone. Then replace the speed-handling block inside `resolve_movement_phase`:

```python
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
```

with:

```python
        if order.target_speed is not None:
            ship.set_speed(order.target_speed)
            events.append(
                MoveEvent(
                    kind="speed",
                    ship_id=ship.id,
                    detail=f"speed → {ship.speed:.0f}",
                ),
            )
```

(Task 7 will fully rewrite this file; this is the minimal edit to keep it compiling against the new movement model.)

- [ ] **Step 6: Rewrite `tests/test_movement.py`**

The old tests targeted the deleted `accelerate`/`decelerate`/`CombustionError` API. Replace the file entirely:

```python
"""Tests for spatial.movement (combustion cost helper)."""
from __future__ import annotations

from spacefleet.spatial.movement import combustion_cost


def test_cost_zero_within_max() -> None:
    assert combustion_cost(current_speed=0.0, target_speed=10.0, max_speed=20.0) == 0
    assert combustion_cost(current_speed=0.0, target_speed=20.0, max_speed=20.0) == 0


def test_cost_only_over_portion() -> None:
    # 0 → 25 with max 20 = 5 over
    assert combustion_cost(current_speed=0.0, target_speed=25.0, max_speed=20.0) == 5


def test_cost_already_over_burn_delta_only() -> None:
    # 22 → 25 with max 20 = 3 GU additional over-burn
    assert combustion_cost(current_speed=22.0, target_speed=25.0, max_speed=20.0) == 3


def test_cost_decelerating_over_burn_is_free() -> None:
    # 25 → 20 = fully leaving over-burn, free
    assert combustion_cost(current_speed=25.0, target_speed=20.0, max_speed=20.0) == 0
    # 25 → 22 = still over but decreasing, free
    assert combustion_cost(current_speed=25.0, target_speed=22.0, max_speed=20.0) == 0


def test_cost_decelerating_within_normal_range_is_free() -> None:
    assert combustion_cost(current_speed=15.0, target_speed=5.0, max_speed=20.0) == 0


def test_cost_rounds_up_fractional_over() -> None:
    # 0 → 20.5 with max 20 = 0.5 over → rounds up to 1
    assert combustion_cost(current_speed=0.0, target_speed=20.5, max_speed=20.0) == 1
```

- [ ] **Step 7: Fix `tests/test_movement_phase.py`**

The existing `test_accelerate_then_drift` test asserts combustion drops from 50 to 40 after an ahead 10 order. Under the new model, 10 is within max so combustion stays 50. Edit `tests/test_movement_phase.py`:

Find:

```python
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
```

Replace with a pair of tests:

```python
def test_accelerate_within_max_is_free():
    ship = _ship("a")
    ship.combustion = 50
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(target_speed=10.0)},
    )
    assert ship.speed == 10.0
    assert ship.combustion == 50  # within max → free
    assert any(e.kind == "speed" for e in log)
    assert any(e.kind == "drift" for e in log)


def test_over_burn_spends_combustion():
    ship = _ship("a")
    ship.combustion = 10
    cap = ship.effective_speed_max
    log = resolve_movement_phase(
        [ship],
        orders={"a": MoveOrder(target_speed=cap + 3)},
    )
    assert ship.speed == cap + 3
    assert ship.combustion == 7
    assert any(e.kind == "speed" for e in log)
```

- [ ] **Step 8: Run new + changed tests**

Run: `uv run pytest tests/test_set_speed_combustion.py tests/test_movement.py tests/test_movement_phase.py -v`
Expected: 8 + 6 + 4 = 18 passed.

- [ ] **Step 9: Run full regression suite**

Run: `uv run pytest -q`
Expected: green. Existing `test_sprint3.py:353` sets `ship.speed = 20.0` directly — bypasses `set_speed`, still works. `test_stances.py` doesn't touch combustion. `test_smoke.py` exercises the multiplayer PvE factory but no ahead commands.

- [ ] **Step 10: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/spatial/movement.py src/spacefleet/models/ship.py src/spacefleet/phases/movement_phase.py tests/test_set_speed_combustion.py tests/test_movement.py tests/test_movement_phase.py
uv run ruff format src/spacefleet/spatial/movement.py src/spacefleet/models/ship.py src/spacefleet/phases/movement_phase.py tests/test_set_speed_combustion.py tests/test_movement.py tests/test_movement_phase.py
uv run mypy --strict src/spacefleet/spatial/movement.py src/spacefleet/models/ship.py src/spacefleet/phases/movement_phase.py
git add src/spacefleet/spatial/movement.py src/spacefleet/models/ship.py src/spacefleet/phases/movement_phase.py tests/test_set_speed_combustion.py tests/test_movement.py tests/test_movement_phase.py
git commit -m "$(cat <<'EOF'
feat(models): combustion is over-burn fuel

Normal speed changes inside [0, effective_speed_max] are free.
Combustion is only spent when raising speed above effective_speed_max
(afterburner), 1 combustion per 1 GU of over-burn.  Deceleration is
always free.  Insufficient combustion clamps the target rather than
raising an error.

spatial/movement.py is reduced to a pure combustion_cost helper.
Ship.set_speed becomes the single public speed-change API; the
movement phase resolver calls it directly instead of the deleted
accelerate/decelerate wrappers.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Task 2: `Ship.subsystems` migration

**Files:**
- Modify: `src/spacefleet/models/ship.py:63-67` (field block) + `:170,314,348-358` (use sites)
- Test: `tests/test_ship_subsystems_migration.py`

Ship currently carries four `subsystem_*: bool` flags. Migrate to a single `subsystems: Subsystems` field, exposing the four old names as forwarding properties so `cli/display.py:129-132`, `combat/resolution.py:115`, `combat/critical_hits.py:271-332`, and `net/game_room.py:397` keep working unchanged.

- [ ] **Step 1: Write failing test**

`tests/test_ship_subsystems_migration.py`:
```python
"""Ship.subsystems is the source of truth; legacy attrs forward to it."""
from __future__ import annotations

from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.models.subsystems import Subsystems


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_ship_has_subsystems_field() -> None:
    ship = _ship()
    assert isinstance(ship.subsystems, Subsystems)
    assert ship.subsystems.all_operational()


def test_legacy_attrs_read_from_subsystems() -> None:
    ship = _ship()
    ship.subsystems.engines = False
    assert ship.subsystem_engines is False
    assert ship.subsystem_generator is True


def test_legacy_attrs_write_through_to_subsystems() -> None:
    ship = _ship()
    ship.subsystem_weapons = False
    assert ship.subsystems.weapons is False
    assert not ship.subsystems.all_operational()


def test_independent_ship_instances_do_not_share_subsystems() -> None:
    a = _ship()
    b = _ship()
    a.subsystem_deck = False
    assert b.subsystem_deck is True
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_ship_subsystems_migration.py -v`
Expected: `test_ship_has_subsystems_field` FAILS (`Ship` has no attribute `subsystems`).

- [ ] **Step 3: Modify `Ship` field block**

In `src/spacefleet/models/ship.py`, replace the `# ── subsystem stubs ──` block (lines ~63-67):

```python
    # ── subsystems ──
    subsystems: Subsystems = field(default_factory=Subsystems)
```

Add the `Subsystems` import at the top, after the other model imports (around line 19, inside the runtime imports block — `Subsystems` is a normal dataclass, not a TYPE_CHECKING-only symbol):

```python
from spacefleet.models.subsystems import Subsystems
```

After the `# ── critical hit state ──` block (before `pending_turn`), add the four forwarding properties:

```python
    # ── legacy subsystem accessors (forward to self.subsystems) ──

    @property
    def subsystem_generator(self) -> bool:
        return self.subsystems.generator

    @subsystem_generator.setter
    def subsystem_generator(self, value: bool) -> None:
        self.subsystems.generator = value

    @property
    def subsystem_deck(self) -> bool:
        return self.subsystems.deck

    @subsystem_deck.setter
    def subsystem_deck(self, value: bool) -> None:
        self.subsystems.deck = value

    @property
    def subsystem_engines(self) -> bool:
        return self.subsystems.engines

    @subsystem_engines.setter
    def subsystem_engines(self, value: bool) -> None:
        self.subsystems.engines = value

    @property
    def subsystem_weapons(self) -> bool:
        return self.subsystems.weapons

    @subsystem_weapons.setter
    def subsystem_weapons(self, value: bool) -> None:
        self.subsystems.weapons = value
```

- [ ] **Step 4: Run new test**

Run: `uv run pytest tests/test_ship_subsystems_migration.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run regression suite**

Run: `uv run pytest -q`
Expected: full suite green. The existing `test_sprint3.py::TestApplyCritical` tests touch `ship.subsystem_*` attributes — the property setters preserve behaviour.

- [ ] **Step 6: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/models/ship.py tests/test_ship_subsystems_migration.py
uv run ruff format src/spacefleet/models/ship.py tests/test_ship_subsystems_migration.py
uv run mypy --strict src/spacefleet/models/ship.py
git add src/spacefleet/models/ship.py tests/test_ship_subsystems_migration.py
git commit -m "$(cat <<'EOF'
refactor(models): Ship owns Subsystems dataclass via property forwarders

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Task 3: `Ship.stance_state` migration

**Files:**
- Modify: `src/spacefleet/models/ship.py:55-57` (fields), `:164-184` (`switch_stance`/`tick_stance_cooldown`)
- Test: `tests/test_ship_stance_migration.py`

Same pattern as Task 2 for the stance pair (`stance` + `stance_cooldown_remaining`). Forward the legacy attribute names. Use `models.stance.can_switch` inside `switch_stance`.

- [ ] **Step 1: Write failing test**

`tests/test_ship_stance_migration.py`:
```python
"""Ship.stance_state is the source of truth; legacy attrs forward to it."""
from __future__ import annotations

from spacefleet.core.types import Stance, Vector2D
from spacefleet.data.demo_data import DAUNTLESS_HULL, make_broadside_kit
from spacefleet.models.ship import Ship
from spacefleet.models.stance import StanceState


def _ship() -> Ship:
    return Ship.from_profile(
        ship_id="a",
        name="A",
        hull=DAUNTLESS_HULL,
        weapons=make_broadside_kit(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_ship_has_stance_state_field() -> None:
    ship = _ship()
    assert isinstance(ship.stance_state, StanceState)
    assert ship.stance_state.stance == Stance.STANDARD
    assert ship.stance_state.cooldown_remaining == 0


def test_legacy_stance_reads_from_state() -> None:
    ship = _ship()
    ship.stance_state.stance = Stance.LOCK_ON
    ship.stance_state.cooldown_remaining = 2
    assert ship.stance == Stance.LOCK_ON
    assert ship.stance_cooldown_remaining == 2


def test_legacy_stance_writes_through_to_state() -> None:
    ship = _ship()
    ship.stance = Stance.RELOAD
    ship.stance_cooldown_remaining = 1
    assert ship.stance_state.stance == Stance.RELOAD
    assert ship.stance_state.cooldown_remaining == 1


def test_tick_stance_cooldown_uses_state() -> None:
    ship = _ship()
    ship.stance_state.cooldown_remaining = 2
    ship.tick_stance_cooldown()
    assert ship.stance_state.cooldown_remaining == 1


def test_independent_ships_do_not_share_state() -> None:
    a = _ship()
    b = _ship()
    a.stance = Stance.LOCK_ON
    a.stance_cooldown_remaining = 2
    assert b.stance == Stance.STANDARD
    assert b.stance_cooldown_remaining == 0
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_ship_stance_migration.py -v`
Expected: FAIL — `Ship` has no attribute `stance_state`.

- [ ] **Step 3: Modify `Ship` stance block**

In `src/spacefleet/models/ship.py`, replace the `# ── stance ──` block (lines ~55-57):

```python
    # ── stance ──
    stance_state: StanceState = field(default_factory=StanceState)
```

Add the import alongside `Subsystems` (Task 2):

```python
from spacefleet.models.stance import StanceState, can_switch
```

(`Stance` is already imported via `core.types`.)

Add forwarding properties below the new subsystem properties:

```python
    # ── legacy stance accessors (forward to self.stance_state) ──

    @property
    def stance(self) -> Stance:
        return self.stance_state.stance

    @stance.setter
    def stance(self, value: Stance) -> None:
        self.stance_state.stance = value

    @property
    def stance_cooldown_remaining(self) -> int:
        return self.stance_state.cooldown_remaining

    @stance_cooldown_remaining.setter
    def stance_cooldown_remaining(self, value: int) -> None:
        self.stance_state.cooldown_remaining = value
```

Replace `switch_stance` and `tick_stance_cooldown`:

```python
    def switch_stance(self, new_stance: Stance) -> bool:
        """Switch to *new_stance* if allowed.  Returns True on success."""
        if new_stance == self.stance_state.stance:
            return True
        if not can_switch(
            self.stance_state,
            deck_operational=self.subsystems.deck,
            morale=self.morale,
        ):
            return False
        from spacefleet.data.stance_registry import StanceRegistry

        self.stance_state.stance = new_stance
        data = StanceRegistry.get_for(new_stance)
        self.stance_state.cooldown_remaining = data.switch_cooldown
        return True

    def tick_stance_cooldown(self) -> None:
        """Decrement stance cooldown by 1 (call once per end-of-turn)."""
        self.stance_state.tick()
```

- [ ] **Step 4: Run new test**

Run: `uv run pytest tests/test_ship_stance_migration.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run regression suite**

Run: `uv run pytest -q`
Expected: green. `tests/test_stances.py` exercises switch + cooldown + morale-blocks-switch and uses the legacy attribute names — the forwarders preserve behaviour.

- [ ] **Step 6: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/models/ship.py tests/test_ship_stance_migration.py
uv run ruff format src/spacefleet/models/ship.py tests/test_ship_stance_migration.py
uv run mypy --strict src/spacefleet/models/ship.py
git add src/spacefleet/models/ship.py tests/test_ship_stance_migration.py
git commit -m "$(cat <<'EOF'
refactor(models): Ship owns StanceState dataclass via property forwarders

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Task 4: Wire `combat/morale_effects` across the combat layer

**Files:**
- Modify: `src/spacefleet/combat/resolution.py:247` and `:384`
- Modify: `src/spacefleet/combat/projectile_resolution.py:152`
- Modify: `src/spacefleet/combat/boarding.py:131-133`
- Modify: `src/spacefleet/combat/critical_hits.py:336-337`
- Test: `tests/test_morale_effects_wiring.py`

Each of these call sites currently inlines a magic morale constant (`-3 * hull_damage`, `-10 * crew_damage`, `-5` per crit). Route them through `combat.morale_effects.*` so the constants live in one place.

- [ ] **Step 1: Write failing test**

`tests/test_morale_effects_wiring.py`:
```python
"""Verify combat call sites use morale_effects helpers, not magic constants."""
from __future__ import annotations

import inspect

from spacefleet.combat import boarding, critical_hits, projectile_resolution, resolution


def _src(module) -> str:
    return inspect.getsource(module)


def test_resolution_uses_apply_hull_damage_morale() -> None:
    src = _src(resolution)
    assert "apply_hull_damage_morale" in src
    assert "-3 * total_hull_damage" not in src
    assert "-3 * hull_damage" not in src


def test_projectile_resolution_uses_apply_hull_damage_morale() -> None:
    src = _src(projectile_resolution)
    assert "apply_hull_damage_morale" in src
    assert "-3 * total_hull_damage" not in src


def test_boarding_uses_apply_boarding_crew_morale() -> None:
    src = _src(boarding)
    assert "apply_boarding_crew_morale" in src
    assert "-10 * result.total_crew_damage" not in src


def test_critical_hits_uses_apply_critical_hit_morale() -> None:
    src = _src(critical_hits)
    assert "apply_critical_hit_morale" in src
    assert "ship.apply_morale_change(-5)" not in src
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_morale_effects_wiring.py -v`
Expected: all 4 tests FAIL — magic constants still present, helper names absent.

- [ ] **Step 3: Edit `combat/resolution.py`**

Add the import at the top with the other `combat` imports:

```python
from spacefleet.combat.morale_effects import apply_hull_damage_morale
```

Replace `combat/resolution.py:247`:

```python
    if total_hull_damage > 0:
        target.take_hull_damage(total_hull_damage)
        apply_hull_damage_morale(target, hull_damage=total_hull_damage)
        result.target_destroyed = not target.alive
```

Replace `combat/resolution.py:384`:

```python
    if hull_damage > 0:
        target.take_hull_damage(hull_damage)
        apply_hull_damage_morale(target, hull_damage=hull_damage)
        result.target_destroyed = not target.alive
```

- [ ] **Step 4: Edit `combat/projectile_resolution.py`**

Add the import:

```python
from spacefleet.combat.morale_effects import apply_hull_damage_morale
```

Replace the `target.apply_morale_change(-3 * total_hull_damage)` line at `:152`:

```python
    if total_hull_damage > 0:
        target.take_hull_damage(total_hull_damage)
        apply_hull_damage_morale(target, hull_damage=total_hull_damage)
        result.target_destroyed = not target.alive
```

- [ ] **Step 5: Edit `combat/boarding.py`**

Add the import:

```python
from spacefleet.combat.morale_effects import apply_boarding_crew_morale
```

Replace the morale-application block at `:131-133`:

```python
    # Crew damage → morale penalty
    apply_boarding_crew_morale(target, crew_damage_count=result.total_crew_damage)
```

- [ ] **Step 6: Edit `combat/critical_hits.py`**

Add the import at the top with the other `combat` imports:

```python
from spacefleet.combat.morale_effects import apply_critical_hit_morale
```

Replace the trailing `ship.apply_morale_change(-5)` block at `:336-337`:

```python
    # Morale penalty for every critical hit
    apply_critical_hit_morale(ship)
```

- [ ] **Step 7: Run wiring + regression tests**

Run: `uv run pytest tests/test_morale_effects_wiring.py tests/test_sprint3.py tests/test_stances.py tests/test_morale_effects.py -v`
Expected: all green. The helper does the same arithmetic so the existing critical/morale assertions in `test_sprint3.py::TestApplyCritical::test_morale_loss_per_crit` still pass.

- [ ] **Step 8: Run full suite**

Run: `uv run pytest -q`
Expected: 99+ passed.

- [ ] **Step 9: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/combat tests/test_morale_effects_wiring.py
uv run ruff format src/spacefleet/combat tests/test_morale_effects_wiring.py
uv run mypy --strict src/spacefleet/combat
git add src/spacefleet/combat/resolution.py src/spacefleet/combat/projectile_resolution.py src/spacefleet/combat/boarding.py src/spacefleet/combat/critical_hits.py tests/test_morale_effects_wiring.py
git commit -m "$(cat <<'EOF'
refactor(combat): route morale changes through morale_effects helpers

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Task 5: Wire `combat/damage` through the resolvers

**Files:**
- Modify: `src/spacefleet/combat/damage.py` — move `HitDetail` here, extend `DamageReport.details: list[HitDetail]`
- Modify: `src/spacefleet/combat/resolution.py:60-97` (`AttackResult` import) and `:196-220` (battery damage block) and `:358-371` (lance damage block)
- Modify: `src/spacefleet/combat/projectile_resolution.py:123-148` (battery damage block)
- Test: `tests/test_damage_details.py`

Make `combat/damage.py` the canonical owner of both the pipeline and the `HitDetail` dataclass. Resolvers stop hand-rolling shield/armor loops.

- [ ] **Step 1: Write failing test**

`tests/test_damage_details.py`:
```python
"""DamageReport now carries per-hit HitDetail records."""
from __future__ import annotations

from spacefleet.combat.damage import DamageReport, HitDetail, apply_damage_pipeline
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


def test_report_has_details_list() -> None:
    report = DamageReport()
    assert report.details == []


def test_pipeline_records_shield_blocks_as_details() -> None:
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
    assert len(report.details) == 2
    assert all(d.blocked_by_shield for d in report.details)


def test_pipeline_records_armor_rolls() -> None:
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
    armor_details = [d for d in report.details if not d.blocked_by_shield]
    assert len(armor_details) == 3
    for d in armor_details:
        assert d.armor_value > 0
        assert 1 <= d.armor_roll <= 6
        assert d.penetrated == (d.armor_roll >= d.armor_value)


def test_resolution_imports_hit_detail_from_damage() -> None:
    """resolution.py should re-import HitDetail from combat.damage."""
    from spacefleet.combat import resolution

    assert resolution.HitDetail is HitDetail
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_damage_details.py -v`
Expected: FAIL — `details` field absent, `HitDetail` not in `combat.damage`.

- [ ] **Step 3: Move `HitDetail` into `combat/damage.py`**

Replace `src/spacefleet/combat/damage.py` entirely:

```python
"""Shield → armor → hull damage pipeline.

Owns the per-hit ``HitDetail`` record and the aggregate
``DamageReport`` returned by :func:`apply_damage_pipeline`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.dice import DiceRoller
from spacefleet.dice import dice as default_dice

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class HitDetail:
    """One individual hit going through the armor-save step."""

    blocked_by_shield: bool = False
    armor_roll: int = 0
    armor_value: int = 0
    penetrated: bool = False
    hull_damage: int = 0


@dataclass
class DamageReport:
    """Aggregate counts + per-hit details for one damage application."""

    shield_blocked: int = 0
    armor_saves: int = 0
    penetrating: int = 0
    hull_damage: int = 0
    details: list[HitDetail] = field(default_factory=list)


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

    Returns a :class:`DamageReport` with per-hit details and mutates
    *target* (shields + hull).  Morale changes are applied separately
    by the caller.
    """
    dr = dice_roller or default_dice
    report = DamageReport()
    if hits <= 0:
        return report

    after_shields = target.absorb_shields(hits)
    report.shield_blocked = hits - after_shields

    for _ in range(report.shield_blocked):
        report.details.append(HitDetail(blocked_by_shield=True))

    if after_shields == 0:
        return report

    if ignores_armor:
        report.penetrating = after_shields
        report.hull_damage = after_shields * damage_per_hit
        for _ in range(after_shields):
            report.details.append(
                HitDetail(penetrated=True, hull_damage=damage_per_hit),
            )
        if report.hull_damage > 0:
            target.take_hull_damage(report.hull_damage)
        return report

    armor = target.armor_for_bearing(relative_bearing)
    for _ in range(after_shields):
        roll = dr.d6()
        detail = HitDetail(armor_roll=roll, armor_value=armor)
        if roll >= armor:
            detail.penetrated = True
            detail.hull_damage = damage_per_hit
            report.penetrating += 1
            report.hull_damage += damage_per_hit
        else:
            report.armor_saves += 1
        report.details.append(detail)

    if report.hull_damage > 0:
        target.take_hull_damage(report.hull_damage)

    return report
```

- [ ] **Step 4: Strip the old `HitDetail` from `combat/resolution.py` and re-export**

In `src/spacefleet/combat/resolution.py`:

1. Delete the local `@dataclass class HitDetail` block (lines ~61-69).
2. Import it from `damage`:

```python
from spacefleet.combat.damage import DamageReport, HitDetail, apply_damage_pipeline
```

3. Add `HitDetail` to `__all__`:

```python
__all__ = ["GUNNERY_COLUMNS", "GUNNERY_TABLE", "HitDetail"]
```

- [ ] **Step 5: Refactor `resolve_battery_attack` damage block**

Replace `src/spacefleet/combat/resolution.py` lines ~196-220 (the `# ── Step 6: damage pipeline ──` block through `result.hit_details.append(detail)` loop) with:

```python
    # ── Step 6: damage pipeline (shields → armor → hull) ──
    incoming_bearing = relative_bearing(
        target.heading,
        bearing_from_to(target.position, attacker.position),
    )
    report = apply_damage_pipeline(
        target=target,
        hits=raw_hits,
        relative_bearing=incoming_bearing,
        damage_per_hit=weapon.weapon.damage_per_hit,
        dice_roller=dr,
    )
    result.shield_blocked = report.shield_blocked
    result.armor_saves = report.armor_saves
    result.hit_details = report.details
    total_hull_damage = report.hull_damage
```

(Keep the existing Brace extra-armor-save loop, Brace hull damage reduction, `apply_hull_damage_morale`, and crit blocks below — they operate on `result.hit_details` which is now `report.details`.)

- [ ] **Step 6: Refactor `resolve_lance_attack` damage block**

Lances bypass armor, so use `ignores_armor=True`. Replace `src/spacefleet/combat/resolution.py` lines ~358-371 (from `# Shields absorb first` through `hull_damage = remaining * weapon.weapon.damage_per_hit`) with:

```python
    report = apply_damage_pipeline(
        target=target,
        hits=raw_hits,
        relative_bearing=0.0,  # ignored when ignores_armor=True
        damage_per_hit=weapon.weapon.damage_per_hit,
        ignores_armor=True,
        dice_roller=dr,
    )
    result.shield_blocked = report.shield_blocked
    remaining = raw_hits - report.shield_blocked
    result.penetrating_hits = report.penetrating
    hull_damage = report.hull_damage
```

The Brace extra-save loop below operates on `remaining` and decrements `result.penetrating_hits` / `hull_damage` — leave that intact.

- [ ] **Step 7: Refactor `projectile_resolution.resolve_projectile_impact`**

Apply the same swap to `src/spacefleet/combat/projectile_resolution.py` lines ~123-148. Add the import:

```python
from spacefleet.combat.damage import apply_damage_pipeline
```

Replace the damage block (from `# ── Damage pipeline ──` through `result.hit_details.append(detail)`) with:

```python
    # ── Damage pipeline ──
    incoming_from = (projectile.bearing + 180.0) % 360.0
    incoming_rel = relative_bearing(target.heading, incoming_from)
    report = apply_damage_pipeline(
        target=target,
        hits=raw_hits,
        relative_bearing=incoming_rel,
        damage_per_hit=weapon.weapon.damage_per_hit,
        dice_roller=dr,
    )
    result.shield_blocked = report.shield_blocked
    result.armor_saves = report.armor_saves
    result.hit_details = report.details
    result.penetrating_hits = report.penetrating
    total_hull_damage = report.hull_damage
```

(The `apply_hull_damage_morale` + crit blocks below stay.)

- [ ] **Step 8: Run damage detail test**

Run: `uv run pytest tests/test_damage_details.py tests/test_damage.py -v`
Expected: all green. `tests/test_damage.py::test_overflow_rolls_armor` still passes because `report.penetrating + report.armor_saves == 3` is unchanged.

- [ ] **Step 9: Run full regression suite**

Run: `uv run pytest -q`
Expected: full suite green. `test_stances.py` checks `result.hit_details` granularity and `test_sprint3.py::TestCriticalHitTable` exercises the crit pipeline — both still work.

- [ ] **Step 10: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/combat tests/test_damage_details.py
uv run ruff format src/spacefleet/combat tests/test_damage_details.py
uv run mypy --strict src/spacefleet/combat
git add src/spacefleet/combat/damage.py src/spacefleet/combat/resolution.py src/spacefleet/combat/projectile_resolution.py tests/test_damage_details.py
git commit -m "$(cat <<'EOF'
refactor(combat): route resolvers through apply_damage_pipeline

Move HitDetail into combat.damage and have battery/lance/projectile
resolvers consume DamageReport.details instead of hand-rolling the
shield/armor loop.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Task 6: `net.GameState` inherits from `core.CoreGameState`

**Files:**
- Modify: `src/spacefleet/core/game_state.py` — rename methods to match `net.GameState`'s naming
- Modify: `tests/test_core_game_state.py` — match renamed methods
- Modify: `src/spacefleet/net/game_state.py:23-93` — drop duplicated fields/methods, inherit from `CoreGameState`
- Test: `tests/test_game_state_inheritance.py`

`CoreGameState` and `net.GameState` carry the same `turn`/`ships`/`dice` fields and the same `get_ship`/`alive_ships`/`is_game_over` methods. Make the server class inherit. First align the method names (`enemies_of` → `enemy_ships_of`, `friendlies_of` → `friendly_ships_of`).

- [ ] **Step 1: Rename `CoreGameState` methods**

Edit `src/spacefleet/core/game_state.py`:

```python
    def enemy_ships_of(self, ship: Ship) -> list[Ship]:
        return [
            s for s in self.ships.values()
            if s.alive and s.faction != ship.faction
        ]

    def friendly_ships_of(self, ship: Ship) -> list[Ship]:
        return [
            s for s in self.ships.values()
            if s.alive and s.faction == ship.faction and s.id != ship.id
        ]
```

(Replace the existing `enemies_of`/`friendlies_of` methods.)

- [ ] **Step 2: Update existing test**

Edit `tests/test_core_game_state.py:30-31`:

```python
    assert state.enemy_ships_of(a) == [b]
    assert state.friendly_ships_of(a) == []
```

Run: `uv run pytest tests/test_core_game_state.py -v`
Expected: 4 passed.

- [ ] **Step 3: Write failing inheritance test**

`tests/test_game_state_inheritance.py`:
```python
"""net.GameState inherits from core.CoreGameState."""
from __future__ import annotations

from spacefleet.core.game_state import CoreGameState
from spacefleet.net.game_state import GameState


def test_game_state_is_core_game_state() -> None:
    assert issubclass(GameState, CoreGameState)


def test_create_pve_state_has_core_methods() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1)
    # Inherited from CoreGameState
    assert hasattr(state, "alive_ships")
    assert hasattr(state, "enemy_ships_of")
    assert hasattr(state, "friendly_ships_of")
    assert hasattr(state, "is_game_over")
    assert callable(state.alive_ships)
    # Server-specific
    assert "alice" in state.player_ships
    assert state.next_projectile_id() == "salvo_1"
```

- [ ] **Step 4: Run, verify failure**

Run: `uv run pytest tests/test_game_state_inheritance.py -v`
Expected: `test_game_state_is_core_game_state` FAILS.

- [ ] **Step 5: Refactor `net/game_state.py`**

Replace lines 23-93 (the entire `@dataclass class GameState` block, fields + lookup methods + game-over). Keep the factory `@classmethod`s and the projectile id helper. New shape:

```python
from spacefleet.core.game_state import CoreGameState


@dataclass
class GameState(CoreGameState):
    """Authoritative server state for one match.

    Extends :class:`CoreGameState` with multiplayer-specific bookkeeping:
    projectiles in flight, per-player ship rosters, kill tally, fired
    flag, and projectile id sequence.
    """

    projectiles: list[Projectile] = field(default_factory=list)
    player_ships: dict[str, list[str]] = field(default_factory=dict)
    ai_ships: list[str] = field(default_factory=list)
    kills: dict[str, int] = field(default_factory=dict)
    fired_this_turn: set[str] = field(default_factory=set)
    _next_proj_id: int = 0

    # ── Multiplayer-only lookups ─────────────────────────────

    def alive_ships_for(self, player_id: str) -> list[Ship]:
        ids = self.player_ships.get(player_id, [])
        return [self.ships[sid] for sid in ids if self.ships[sid].alive]

    def all_ships_list(self) -> list[Ship]:
        return list(self.ships.values())

    def owner_of(self, ship_id: str) -> str | None:
        for pid, sids in self.player_ships.items():
            if ship_id in sids:
                return pid
        return None

    def owner_lookup(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for pid, sids in self.player_ships.items():
            for sid in sids:
                result[sid] = pid
        return result

    # ── Projectile IDs ───────────────────────────────────────

    def next_projectile_id(self) -> str:
        self._next_proj_id += 1
        return f"salvo_{self._next_proj_id}"
```

(Keep the existing `create_pve` / `create_pvp` / `create_mixed` classmethods below unchanged.)

- [ ] **Step 6: Run inheritance + smoke tests**

Run: `uv run pytest tests/test_game_state_inheritance.py tests/test_smoke.py tests/test_core_game_state.py -v`
Expected: all green. `test_smoke.py::test_game_state_create_pve` exercises `create_pve` and `is_game_over` — those keep working via inheritance.

- [ ] **Step 7: Run full suite**

Run: `uv run pytest -q`
Expected: green.

- [ ] **Step 8: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/core/game_state.py src/spacefleet/net/game_state.py tests/test_game_state_inheritance.py tests/test_core_game_state.py
uv run ruff format src/spacefleet/core/game_state.py src/spacefleet/net/game_state.py tests/test_game_state_inheritance.py tests/test_core_game_state.py
uv run mypy --strict src/spacefleet/core/game_state.py src/spacefleet/net/game_state.py
git add src/spacefleet/core/game_state.py src/spacefleet/net/game_state.py tests/test_core_game_state.py tests/test_game_state_inheritance.py
git commit -m "$(cat <<'EOF'
refactor(net): GameState inherits from core.CoreGameState

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Task 7: Wire `phases/movement_phase` into `net/turn_resolver`

**Files:**
- Modify: `src/spacefleet/phases/movement_phase.py` — accept morale-cap responsibility
- Modify: `src/spacefleet/net/turn_resolver.py:313-383` (movement section)
- Test: `tests/test_turn_resolver_movement_phase.py`

The movement phase resolver currently handles speed/turn/drift but not morale caps. Move the morale cap step into `resolve_movement_phase` so the resolver owns *all* per-ship movement state changes. Then `turn_resolver` builds a `dict[str, MoveOrder]` from commands and translates `MoveEvent`s back into the rendering events the existing renderer expects.

- [ ] **Step 1: Extend `MoveOrder` and add morale-cap step**

Edit `src/spacefleet/phases/movement_phase.py`. Add a new `kind="morale_cap"` event variant and apply caps before the speed-change application:

```python
"""Movement phase resolver.

Handles morale speed caps, applies speed/turn orders (spending
combustion through ``Ship.set_speed``), then drifts every alive ship.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spacefleet.models.morale import speed_cap

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship


@dataclass
class MoveOrder:
    """One ship's movement intent for the phase."""

    target_speed: float | None = None
    turn_degrees: float | None = None
    turn_direction: str = ""  # "port" | "starboard" — for renderer


@dataclass
class MoveEvent:
    """Outcome event produced by the phase resolver."""

    kind: str  # "morale_cap" | "speed" | "turn" | "drift"
    ship_id: str
    detail: str = ""
    old_speed: float = 0.0
    new_speed: float = 0.0
    turn_direction: str = ""
    turn_degrees: float = 0.0
    heading_before: float = 0.0
    heading_after: float = 0.0


def resolve_movement_phase(
    ships: list[Ship],
    orders: dict[str, MoveOrder],
    *,
    drift_fraction: float = 0.5,
) -> list[MoveEvent]:
    """Apply morale caps + orders + drift; return events.

    Order is:

    1. Morale-driven speed cap (``models.morale.speed_cap``).
    2. Per-ship speed / turn orders (combustion spent via ``Ship.set_speed``).
    3. Half-turn drift for every alive ship.
    """
    events: list[MoveEvent] = []

    # 1. Morale caps
    for ship in ships:
        if not ship.alive:
            continue
        cap = speed_cap(ship.morale_state(), ship.effective_speed_max)
        if ship.speed > cap:
            prev = ship.speed
            ship.speed = cap
            events.append(
                MoveEvent(
                    kind="morale_cap",
                    ship_id=ship.id,
                    old_speed=prev,
                    new_speed=cap,
                    detail=f"morale cap → {cap:.0f}",
                ),
            )

    # 2. Orders
    for ship in ships:
        if not ship.alive:
            continue
        order = orders.get(ship.id)
        if order is None:
            continue

        if order.target_speed is not None:
            prev = ship.speed
            ship.set_speed(order.target_speed)
            events.append(
                MoveEvent(
                    kind="speed",
                    ship_id=ship.id,
                    old_speed=prev,
                    new_speed=ship.speed,
                    detail=f"speed → {ship.speed:.0f}",
                ),
            )

        if order.turn_degrees is not None and order.turn_degrees != 0.0:
            ship.apply_turn(order.turn_degrees)
            events.append(
                MoveEvent(
                    kind="turn",
                    ship_id=ship.id,
                    turn_direction=order.turn_direction,
                    turn_degrees=abs(order.turn_degrees),
                    detail=f"{order.turn_degrees:+.0f}°",
                ),
            )

    # 3. Drift
    for ship in ships:
        if not ship.alive:
            continue
        before, after = ship.apply_drift(drift_fraction)
        events.append(
            MoveEvent(
                kind="drift",
                ship_id=ship.id,
                heading_before=before,
                heading_after=after,
                detail=f"hdg {before:.0f}→{after:.0f}",
            ),
        )

    return events
```

- [ ] **Step 2: Update existing movement_phase test**

`tests/test_movement_phase.py` checks event `kind` and basic position changes. The existing assertions still pass because the morale-cap step is a no-op for ships at full morale. Verify:

Run: `uv run pytest tests/test_movement_phase.py -v`
Expected: 3 passed.

- [ ] **Step 3: Write failing turn_resolver integration test**

`tests/test_turn_resolver_movement_phase.py`:
```python
"""turn_resolver delegates the movement section to resolve_movement_phase."""
from __future__ import annotations

import inspect

from spacefleet.net import turn_resolver
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState


def test_turn_resolver_imports_resolve_movement_phase() -> None:
    src = inspect.getsource(turn_resolver)
    assert "from spacefleet.phases.movement_phase import" in src
    assert "resolve_movement_phase" in src


def test_ahead_command_spends_combustion_through_phase() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    ship_id = state.player_ships["alice"][0]
    ship = state.get_ship(ship_id)
    ship.combustion = 50
    ship.speed = 0.0

    cmd = Command(action="ahead", args={"speed": 10.0})
    turn_resolver.resolve_turn(state, {ship_id: cmd})

    # Ship accelerated and spent combustion (10 GU → 10 combustion)
    assert ship.combustion == 40
    assert ship.speed == 10.0
```

- [ ] **Step 4: Run, verify failure**

Run: `uv run pytest tests/test_turn_resolver_movement_phase.py -v`
Expected: both FAIL — phase import absent, combustion still at 50.

- [ ] **Step 5: Refactor `net/turn_resolver.py` movement section**

Add the import at the top:

```python
from spacefleet.phases.movement_phase import MoveOrder, MoveEvent, resolve_movement_phase
```

Drop the `speed_cap` import (movement_phase owns it now). Replace lines 313-383 (the morale-cap block, the speed/turn command loop, **and** the drift loop) with:

```python
    # ── 2. MOVEMENT SUB-PHASE ────────────────────────────────
    move_orders: dict[str, MoveOrder] = {}
    for ship_id, cmd in commands.items():
        ship = state.ships.get(ship_id)
        if ship is None or not ship.alive:
            continue
        if cmd.action == "ahead":
            move_orders[ship_id] = MoveOrder(target_speed=cmd.args["speed"])
        elif cmd.action == "stop":
            move_orders[ship_id] = MoveOrder(target_speed=0.0)
        elif cmd.action == "turn":
            degrees = cmd.args["degrees"]
            if cmd.args["direction"] == "port":
                degrees = -degrees
            move_orders[ship_id] = MoveOrder(
                turn_degrees=degrees,
                turn_direction=cmd.args["direction"],
            )

    move_events = resolve_movement_phase(
        state.alive_ships(),
        move_orders,
        drift_fraction=0.5,
    )
    for ev in move_events:
        ship = state.ships[ev.ship_id]
        if ev.kind in ("morale_cap", "speed"):
            log.add(
                SpeedChangeEvent(ship=ship, old_speed=ev.old_speed, new_speed=ev.new_speed),
            )
        elif ev.kind == "turn":
            log.add(
                TurnOrderEvent(
                    ship=ship,
                    direction=ev.turn_direction,
                    degrees=ev.turn_degrees,
                ),
            )
        elif ev.kind == "drift":
            log.add(
                DriftEvent(
                    ship=ship,
                    old_pos_str=repr(ship.position),
                    heading_before=ev.heading_before,
                    heading_after=ev.heading_after,
                ),
            )

    # Projectiles advance (still part of the movement sub-phase)
    movements = move_projectiles(state.projectiles, fraction=0.5)
    for proj, old_pos, new_pos in movements:
        log.add(SalvoMoveEvent(proj=proj, old_pos=old_pos, new_pos=new_pos))

    # Check projectile collisions
    impacts = check_projectile_collisions(
        movements,
        state.all_ships_list(),
        state.dice,
    )
    for proj, target, result in impacts:
        log.add(SalvoImpactEvent(proj=proj, target=target, result=result))
        if result.target_destroyed:
            _credit_kill(state, proj.attacker_id, result.target_name, log)

    # Cleanup expired projectiles
    expired = cleanup_projectiles(state.projectiles)
    impact_projs = {id(e.proj) for e in log.events if isinstance(e, SalvoImpactEvent)}
    for proj in expired:
        if id(proj) not in impact_projs:
            log.add(SalvoExpiredEvent(proj=proj))
```

(The drift loop that previously sat below the projectile cleanup is gone — drift now happens inside `resolve_movement_phase`.)

- [ ] **Step 6: Run integration test**

Run: `uv run pytest tests/test_turn_resolver_movement_phase.py -v`
Expected: 2 passed.

- [ ] **Step 7: Run full regression suite**

Run: `uv run pytest -q`
Expected: green. `test_smoke.py` exercises `create_pve`; the existing PvE flow must still work end-to-end.

- [ ] **Step 8: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/phases src/spacefleet/net/turn_resolver.py tests/test_turn_resolver_movement_phase.py tests/test_movement_phase.py
uv run ruff format src/spacefleet/phases src/spacefleet/net/turn_resolver.py tests/test_turn_resolver_movement_phase.py tests/test_movement_phase.py
uv run mypy --strict src/spacefleet/phases src/spacefleet/net/turn_resolver.py
git add src/spacefleet/phases/movement_phase.py src/spacefleet/net/turn_resolver.py tests/test_turn_resolver_movement_phase.py
git commit -m "$(cat <<'EOF'
refactor(net): turn_resolver routes movement through phases/movement_phase

Phase resolver now owns morale caps + speed/turn/drift in one place.
turn_resolver translates MoveEvent records into the existing render
event types so the server renderer keeps working unchanged.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Task 8: `EventBus` publishers + first subscriber

**Files:**
- Modify: `src/spacefleet/core/game_state.py` — add `events: EventBus` field
- Modify: `src/spacefleet/net/turn_resolver.py` — publish each `TurnEvent`
- Test: `tests/test_event_publish.py`

Make `core.events.EventBus` a real participant. Every `TurnEvent` added to the `TurnLog` is also published on `state.events`, so subscribers (UI, AI observers, future replay tooling) can hook in without polling the log.

- [ ] **Step 1: Write failing test**

`tests/test_event_publish.py`:
```python
"""turn_resolver publishes each TurnEvent on CoreGameState.events."""
from __future__ import annotations

from spacefleet.core.events import EventBus
from spacefleet.net import turn_resolver
from spacefleet.net.commands import Command
from spacefleet.net.game_state import GameState
from spacefleet.net.turn_resolver import DriftEvent, SpeedChangeEvent, TurnEvent


def test_state_has_event_bus() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    assert isinstance(state.events, EventBus)


def test_subscriber_receives_speed_change() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    received: list[SpeedChangeEvent] = []
    state.events.subscribe(SpeedChangeEvent, received.append)

    ship_id = state.player_ships["alice"][0]
    state.get_ship(ship_id).combustion = 50
    cmd = Command(action="ahead", args={"speed": 5.0})
    turn_resolver.resolve_turn(state, {ship_id: cmd})

    assert len(received) >= 1
    assert any(ev.new_speed == 5.0 for ev in received)


def test_subscriber_receives_drift() -> None:
    state = GameState.create_pve(["alice"], ships_per_player=1, seed=1)
    received: list[DriftEvent] = []
    state.events.subscribe(DriftEvent, received.append)

    ship_id = state.player_ships["alice"][0]
    cmd = Command(action="pass", args={})
    turn_resolver.resolve_turn(state, {ship_id: cmd})

    # Every alive ship drifts → at least one DriftEvent
    assert len(received) >= 1
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_event_publish.py -v`
Expected: `test_state_has_event_bus` FAILS (`CoreGameState` has no `events` attribute).

- [ ] **Step 3: Add `events` field to `CoreGameState`**

Edit `src/spacefleet/core/game_state.py`:

```python
from spacefleet.core.events import EventBus
from spacefleet.dice import DiceRoller
```

Inside the `CoreGameState` dataclass, add a new field after `dice`:

```python
    events: EventBus = field(default_factory=EventBus)
```

- [ ] **Step 4: Publish on every `log.add` in `turn_resolver`**

Edit `src/spacefleet/net/turn_resolver.py`. Change the `TurnLog.add` method (lines ~167-169) so it stays a pure list append (the publishing happens at call sites — keeps `TurnLog` decoupled from state).

Better approach: route through a small helper at the top of `resolve_turn`:

```python
    log = TurnLog(turn=state.turn)
    state.fired_this_turn.clear()

    def emit(event: TurnEvent) -> None:
        log.add(event)
        state.events.publish(event)
```

Then **replace every `log.add(...)` call inside `resolve_turn` with `emit(...)`**. This is a mechanical rename — there are roughly 18 call sites across the fire, lightning strike, movement, projectile, end-of-turn, and credit-kill blocks. The helper `_credit_kill` also calls `log.add` — pass `emit` into it instead, or have `_credit_kill` accept the bus too.

Pragmatic option: add an `events: EventBus` parameter to `_credit_kill`, default to `None` so existing callers don't break, and have `resolve_turn` pass `state.events`:

```python
def _credit_kill(
    state: GameState,
    killer_ship_id: str,
    target_name: str,
    log: TurnLog,
    *,
    events: EventBus | None = None,
) -> None:
    ...
    def emit(event: TurnEvent) -> None:
        log.add(event)
        if events is not None:
            events.publish(event)
    # then replace `log.add(...)` with `emit(...)` inside this function
```

Add `from spacefleet.core.events import EventBus` to the `turn_resolver` imports.

- [ ] **Step 5: Run publish test**

Run: `uv run pytest tests/test_event_publish.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run regression + smoke + suite**

Run: `uv run pytest -q`
Expected: full suite green. Existing tests don't subscribe to the bus; publish is a no-op for them.

- [ ] **Step 7: Lint + mypy + format + commit**

```bash
uv run ruff check src/spacefleet/core/game_state.py src/spacefleet/net/turn_resolver.py tests/test_event_publish.py
uv run ruff format src/spacefleet/core/game_state.py src/spacefleet/net/turn_resolver.py tests/test_event_publish.py
uv run mypy --strict src/spacefleet/core/game_state.py src/spacefleet/net/turn_resolver.py
git add src/spacefleet/core/game_state.py src/spacefleet/net/turn_resolver.py tests/test_event_publish.py
git commit -m "$(cat <<'EOF'
feat(core): publish TurnEvents on CoreGameState.events bus

CoreGameState now owns an EventBus; turn_resolver publishes each
TurnEvent on it as well as appending to TurnLog.  Subscribers (UI,
AI observers, future replay tooling) can hook in without polling.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Self-Review

**Spec coverage of the 8 open items:**

| Open item | Task |
|---|---|
| `Ship.set_speed` doesn't spend combustion | Task 1 |
| `Subsystems` not wired into Ship | Task 2 |
| `StanceState` not wired into Ship | Task 3 |
| `morale_effects` constants duplicated in resolution/boarding/critical_hits | Task 4 |
| `combat/damage` parallel API | Task 5 |
| `net/game_state.GameState` doesn't extend `CoreGameState` | Task 6 |
| `phases/movement_phase` not called from `net/turn_resolver` | Task 7 |
| `core/events.EventBus` has no publishers | Task 8 |

`phases/shooting_phase` not called from `net/turn_resolver` is **explicitly out of scope** (see "Out of scope" section above) and tracked as a follow-up.

**Type consistency:**
- `Subsystems` field name is `subsystems` (Task 2) — used by `switch_stance` in Task 3 (`self.subsystems.deck`), consistent.
- `StanceState` field name is `stance_state` (Task 3) — used by `tick_stance_cooldown`, consistent.
- `MoveOrder` (Task 7) carries `turn_direction: str` for the renderer translation — referenced by `MoveEvent.turn_direction` in the same task.
- `HitDetail` lives in `combat.damage` (Task 5) and is re-exported from `combat.resolution` for back-compat — verified in `tests/test_damage_details.py::test_resolution_imports_hit_detail_from_damage`.
- `CoreGameState.enemy_ships_of` / `friendly_ships_of` (Task 6) match `net.GameState`'s historical names — Task 6 Step 1 renames `CoreGameState`'s methods to align with `net.GameState`'s call sites.

**Placeholder scan:** Every step has either complete code or an exact command. The phrase "follow-up" appears once, in the out-of-scope note for `shooting_phase`. No "TBD" / "implement later" / "handle edge cases" patterns.

**Risk callouts:**
- Task 1 changes the semantics of the combustion gauge, not acceleration inside the normal range. Normal `ahead`/`stop` commands are free; only explicit over-burn (target > effective_speed_max) drains combustion. The multiplayer demo, CLI `ahead`, and AI controller all issue normal speeds — none should notice a behavioural change. Regression watch: `test_smoke.py::test_game_state_create_pve` and `tests/test_sprint3.py::TestMoraleSpeedPenalties`.
- Task 1 deletes `spatial.movement.accelerate`, `spatial.movement.decelerate`, and `spatial.movement.CombustionError`. `phases/movement_phase.py` is the only caller — updated in the same commit. Any external tool still importing those symbols will break; none currently does.
- Task 5 moves `HitDetail` between modules. The `__all__` re-export in `resolution.py` preserves `from spacefleet.combat.resolution import HitDetail` for any external importer.
- Task 7 deletes the standalone drift loop in `turn_resolver` (drift now runs inside `resolve_movement_phase`). Verify the projectile collision step still sees ship positions consistent with the post-drift state — it does, because both old and new code drift after speed/turn application.

---

# Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-13-sprint1-4-integration-cleanup.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review per task, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
