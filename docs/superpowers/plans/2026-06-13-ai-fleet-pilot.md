# AI Fleet Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `net/ai_controller.py` from hulk-only fire-or-pass into a fleet pilot that maneuvers, fires, and manages stance, controllable over an explicit ship-id set.

**Architecture:** A greedy per-ship policy inside `AIController`. For each controlled ship: manage stance (free side effect), pick the nearest enemy (shields-down preference among firing solutions), then either `fire` the best bearing weapon, `turn` to face, or `ahead` to close. Each ship submits one `Command` per turn (engine constraint). Behavior is deterministic given `state.dice`.

**Tech Stack:** Python 3.12, `uv`, pytest, ruff, mypy --strict. Geometry helpers in `spatial/geometry.py`; commands in `net/commands.py`.

**Spec:** `docs/superpowers/specs/2026-06-13-ai-fleet-pilot-design.md`

---

## File Structure

- **Modify (rewrite):** `src/spacefleet/net/ai_controller.py` — the `AIController` class. New `generate_commands(state, controlled_ids=None)` plus private helpers `_decide`, `_choose_target`, `_firing_solution`, `_manage_stance`.
- **Create:** `tests/test_ai_fleet_pilot.py` — unit + integration tests.
- **Unchanged:** `src/spacefleet/net/game_room.py` — keeps calling `self.ai.generate_commands(self.state)` (default arg preserves wiring).

## Reference: APIs this plan uses (already exist)

- `Stance.STANDARD`, `Stance.LOCK_ON`, `Stance.BRACE_FOR_IMPACT` (note the full name).
- `ship.switch_stance(new_stance) -> bool`; `ship.stance` ; `ship.stance_cooldown_remaining: int`.
- `ship.effective_speed_max: float`; `ship.effective_turn_rate: float`; `ship.hull.hull_hits: int`; `ship.hull_current: int`; `ship.shields_current: int`; `ship.weapons: list[WeaponMount]`.
- `WeaponMount.slot_id: int`, `WeaponMount.arc: Arc`, `WeaponMount.weapon.range: float`, `WeaponMount.weapon.strength: int`.
- `state.ai_ships: list[str]`; `state.get_ship(id) -> Ship`; `state.enemy_ships_of(ship) -> list[Ship]`; `state.dice.chance(p) -> bool`.
- `bearing_from_to(a, b) -> float`; `distance(a, b) -> float`; `is_in_arc(heading, bearing, arc) -> bool`; `relative_bearing(heading, abs_bearing) -> float` (positive = starboard/right, negative = port/left, range (-180, 180]).
- `Command(ship_id=..., action="fire"|"turn"|"ahead"|"stop"|"pass", args={...})`.

---

## Task 1: `controlled_ids` parameter (plumbing + target helper)

**Files:**
- Modify: `src/spacefleet/net/ai_controller.py`
- Test: `tests/test_ai_fleet_pilot.py`

- [ ] **Step 1: Write the failing test**

```python
"""AI fleet pilot — controlled-ship selection and targeting."""

from __future__ import annotations

import dataclasses

from spacefleet.core.types import Arc, Faction, Stance, Vector2D
from spacefleet.data.demo_data import HULK_HULL, SALVAGE_GUN
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.models.weapon import WeaponMount
from spacefleet.net.ai_controller import AIController
from spacefleet.net.game_state import GameState

# The HULK hull is immobile (speed/turn_rate 0) with a wide DORSAL gun — useless
# for testing maneuver/arc logic. Build a mobile ship with a narrow PROW weapon.
_MOBILE_HULL = dataclasses.replace(HULK_HULL, speed=20.0, turn_rate=45.0, hull_hits=8)
_PROW_GUN = WeaponMount(slot_id=1, slot_name="Gun", arc=Arc.PROW, weapon=SALVAGE_GUN)


def _ship(sid: str, faction: Faction, pos: Vector2D, heading: float = 0.0) -> Ship:
    hull = dataclasses.replace(_MOBILE_HULL, faction=faction)
    s = Ship.from_profile(
        sid, sid, hull, [dataclasses.replace(_PROW_GUN)], position=pos, heading=heading
    )
    s.faction = faction
    return s


def _state(*ships: Ship) -> GameState:
    state = GameState(dice=DiceRoller(seed=1))
    for s in ships:
        state.ships[s.id] = s
    return state


def test_controlled_ids_restricts_commands() -> None:
    a = _ship("a", Faction.CHAOS_FLEET, Vector2D(0, 0))
    b = _ship("b", Faction.CHAOS_FLEET, Vector2D(5, 0))
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 100))
    state = _state(a, b, enemy)
    ai = AIController()
    cmds = ai.generate_commands(state, controlled_ids=["a"])
    assert set(cmds.keys()) == {"a"}


def test_default_controls_ai_ships() -> None:
    hulk = _ship("ai_hulk_1", Faction.CHAOS_FLEET, Vector2D(0, 0))
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 100))
    state = _state(hulk, enemy)
    state.ai_ships.append("ai_hulk_1")
    ai = AIController()
    cmds = ai.generate_commands(state)
    assert set(cmds.keys()) == {"ai_hulk_1"}
```

> The PROW weapon (range 30, strength 1) has a narrow ±45° arc, so an enemy off
> to the side is genuinely out-of-arc; `turn_rate=45` and `speed=20` make the
> maneuver branches exercise real values; `hull_hits=8` makes the <40% brace
> threshold (3.2) reachable by setting `hull_current=1`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_fleet_pilot.py -q`
Expected: FAIL — `generate_commands()` got an unexpected keyword argument `controlled_ids`.

- [ ] **Step 3: Rewrite `ai_controller.py` with the new skeleton**

Replace the entire file contents with:

```python
"""AI controller — generates commands for AI-controlled ships.

A greedy per-ship fleet pilot: each controlled ship manages its stance,
picks the nearest enemy (preferring one already exposed by downed shields
when a firing solution exists), then fires the best bearing weapon, turns
to face, or accelerates to close.  One ``Command`` per ship per turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.net.commands import Command
from spacefleet.spatial.geometry import bearing_from_to, distance, is_in_arc

if TYPE_CHECKING:
    from spacefleet.models.ship import Ship
    from spacefleet.models.weapon import WeaponMount
    from spacefleet.net.game_state import GameState

# Engage at ~60% of the ship's best weapon range.
ENGAGE_RANGE_FRACTION = 0.6
# Brace when hull drops below this fraction of max.
BRACE_HULL_FRACTION = 0.4


class AIController:
    """Greedy fleet pilot.  One command per alive controlled ship per turn."""

    def __init__(self, fire_chance: float = 1.0) -> None:
        self.fire_chance = fire_chance

    def generate_commands(
        self,
        state: GameState,
        controlled_ids: list[str] | None = None,
    ) -> dict[str, Command]:
        ids = controlled_ids if controlled_ids is not None else state.ai_ships
        commands: dict[str, Command] = {}
        for ship_id in ids:
            ship = state.ships.get(ship_id)
            if ship is None or not ship.alive:
                continue
            commands[ship_id] = self._decide(ship, state)
        return commands

    def _decide(self, ship: Ship, state: GameState) -> Command:
        if not ship.weapons:
            return Command(ship_id=ship.id, action="pass")
        enemies = [e for e in state.enemy_ships_of(ship) if e.alive]
        if not enemies:
            return Command(ship_id=ship.id, action="pass")
        return Command(ship_id=ship.id, action="pass")  # decision logic added in later tasks

    def _choose_target(self, ship: Ship, enemies: list[Ship]) -> Ship:
        """Nearest alive enemy; among those in a firing solution, prefer
        a shields-down target.  Deterministic tie-break by id."""
        in_solution = [e for e in enemies if self._firing_solution(ship, e) is not None]
        exposed = [e for e in in_solution if e.shields_current == 0]
        pool = exposed or enemies
        return min(pool, key=lambda e: (distance(ship.position, e.position), e.id))

    def _firing_solution(self, ship: Ship, target: Ship) -> WeaponMount | None:
        """Best (highest-strength) weapon that bears on *target* in-arc and
        in-range, or None."""
        bearing = bearing_from_to(ship.position, target.position)
        dist = distance(ship.position, target.position)
        candidates = [
            w
            for w in ship.weapons
            if dist <= w.weapon.range and is_in_arc(ship.heading, bearing, w.arc)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda w: w.weapon.strength)

    def _manage_stance(self, ship: Ship, target: Ship) -> None:
        """Free stance side effect (filled in Task 5)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_fleet_pilot.py -q`
Expected: PASS (2 tests). `_choose_target` / `_firing_solution` exist but aren't asserted yet.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src
git add src/spacefleet/net/ai_controller.py tests/test_ai_fleet_pilot.py
git commit -m "feat(ai): controllable-ship-set skeleton + targeting helper"
```

---

## Task 2: Fire when a solution exists

**Files:**
- Modify: `src/spacefleet/net/ai_controller.py` (`_decide`)
- Test: `tests/test_ai_fleet_pilot.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fires_when_enemy_in_arc_and_range() -> None:
    # Hulk weapons fire forward (prow); enemy dead ahead (north = heading 0).
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    state = _state(atk, enemy)
    ai = AIController()
    cmd = ai.generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.action == "fire"
    assert cmd.args["slot"] == atk.weapons[0].slot_id
    assert abs(cmd.args["bearing"] - 0.0) < 1.0  # bearing to due-north target
```

> If this test fails because the hulk's weapon is out of range or arc for a
> target 3 GU due north, adjust the enemy position to sit inside the weapon's
> prow arc and range (inspect `make_hulk_weapons()` arc/range), keeping the
> target dead ahead so the bearing assertion holds.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_fleet_pilot.py::test_fires_when_enemy_in_arc_and_range -v`
Expected: FAIL — `cmd.action == "pass"`, not `"fire"`.

- [ ] **Step 3: Implement the fire branch in `_decide`**

Replace the placeholder final line of `_decide`
(`return Command(ship_id=ship.id, action="pass")  # decision logic added in later tasks`)
with:

```python
        target = self._choose_target(ship, enemies)
        self._manage_stance(ship, target)

        weapon = self._firing_solution(ship, target)
        if weapon is not None and (
            self.fire_chance >= 1.0 or state.dice.chance(self.fire_chance)
        ):
            bearing = bearing_from_to(ship.position, target.position)
            return Command(
                ship_id=ship.id,
                action="fire",
                args={"slot": weapon.slot_id, "bearing": bearing},
            )
        return Command(ship_id=ship.id, action="pass")  # maneuver added in Task 4
```

> The single `weapon is not None` guard narrows `weapon` to non-None for both the
> dice check and `.slot_id`/bearing — mypy-clean. `fire_chance >= 1.0` short-
> circuits so the default always fires without consuming a dice roll; lower
> values roll `state.dice.chance`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_fleet_pilot.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src
git add src/spacefleet/net/ai_controller.py tests/test_ai_fleet_pilot.py
git commit -m "feat(ai): fire the best bearing weapon when a solution exists"
```

---

## Task 3: Shields-down target preference

**Files:**
- Test: `tests/test_ai_fleet_pilot.py` (asserts existing `_choose_target` logic)

- [ ] **Step 1: Write the failing-then-passing test**

```python
def test_prefers_shields_down_target_in_solution() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    shielded = _ship("shield", Faction.IMPERIAL_NAVY, Vector2D(0, 2))
    exposed = _ship("exposed", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    exposed.shields_current = 0
    shielded.shields_current = max(1, shielded.shields_current)
    state = _state(atk, shielded, exposed)
    ai = AIController()
    target = ai._choose_target(atk, [shielded, exposed])
    assert target.id == "exposed"
```

> Place both enemies inside the prow arc and weapon range so both are "in
> solution"; the nearer one is shielded, so a naive nearest-pick would choose
> it — the test proves the shields-down preference overrides distance.

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_fleet_pilot.py::test_prefers_shields_down_target_in_solution -v`
Expected: PASS (logic already implemented in Task 1's `_choose_target`).

> This task is a coverage lock on existing behavior. If it FAILS, the bug is in
> `_choose_target`: confirm `exposed`/`pool` selection prefers `shields_current
> == 0` ships before falling back to all enemies.

- [ ] **Step 3: Gate + commit**

```bash
uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src
git add tests/test_ai_fleet_pilot.py
git commit -m "test(ai): lock shields-down target preference"
```

---

## Task 4: Maneuver — turn to face, else close distance

**Files:**
- Modify: `src/spacefleet/net/ai_controller.py` (`_decide` maneuver branch + `_maneuver` helper)
- Test: `tests/test_ai_fleet_pilot.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_turns_toward_enemy_outside_arc() -> None:
    # Enemy off the starboard side (east), ship facing north → must turn starboard.
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(50, 0))
    state = _state(atk, enemy)
    cmd = AIController().generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.action == "turn"
    assert cmd.args["direction"] == "starboard"
    assert cmd.args["degrees"] > 0


def test_closes_distance_when_far_and_ahead() -> None:
    # Enemy far but dead ahead (in arc, out of range) → accelerate.
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 500))
    state = _state(atk, enemy)
    cmd = AIController().generate_commands(state, controlled_ids=["atk"])["atk"]
    assert cmd.action == "ahead"
    assert cmd.args["speed"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_fleet_pilot.py -k "turns_toward or closes_distance" -v`
Expected: FAIL — both currently return `pass`.

- [ ] **Step 3: Implement maneuver**

First extend the geometry import at the top of the file to add `relative_bearing`:

```python
from spacefleet.spatial.geometry import (
    bearing_from_to,
    distance,
    is_in_arc,
    relative_bearing,
)
```

In `_decide`, replace the final `return Command(ship_id=ship.id, action="pass")  # maneuver added in Task 4` with:

```python
        return self._maneuver(ship, target)
```

Add this method to `AIController`:

```python
    def _maneuver(self, ship: Ship, target: Ship) -> Command:
        bearing = bearing_from_to(ship.position, target.position)
        best_range = max(w.weapon.range for w in ship.weapons)
        # Use the widest-arc weapon to decide "is the target roughly ahead?"
        any_in_arc = any(is_in_arc(ship.heading, bearing, w.arc) for w in ship.weapons)

        if not any_in_arc:
            rel = relative_bearing(ship.heading, bearing)  # + = starboard, - = port
            turn_cap = ship.effective_turn_rate
            degrees = min(abs(rel), turn_cap)
            if degrees <= 0.0:
                return Command(ship_id=ship.id, action="stop")
            direction = "starboard" if rel > 0 else "port"
            return Command(
                ship_id=ship.id,
                action="turn",
                args={"direction": direction, "degrees": degrees},
            )

        dist = distance(ship.position, target.position)
        if dist > best_range * ENGAGE_RANGE_FRACTION:
            speed = ship.effective_speed_max
            return Command(ship_id=ship.id, action="ahead", args={"speed": speed})

        return Command(ship_id=ship.id, action="stop")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_fleet_pilot.py -q`
Expected: PASS (all tests so far).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src
git add src/spacefleet/net/ai_controller.py tests/test_ai_fleet_pilot.py
git commit -m "feat(ai): maneuver to face the target, then close distance"
```

---

## Task 5: Stance management

**Files:**
- Modify: `src/spacefleet/net/ai_controller.py` (`_manage_stance`)
- Test: `tests/test_ai_fleet_pilot.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_braces_when_crippled() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    atk.hull_current = 1  # well below 40% of max
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 3))
    state = _state(atk, enemy)
    AIController().generate_commands(state, controlled_ids=["atk"])
    assert atk.stance == Stance.BRACE_FOR_IMPACT


def test_locks_on_when_engaging_healthy() -> None:
    atk = _ship("atk", Faction.CHAOS_FLEET, Vector2D(0, 0), heading=0.0)
    enemy = _ship("e", Faction.IMPERIAL_NAVY, Vector2D(0, 3))  # within best range
    state = _state(atk, enemy)
    AIController().generate_commands(state, controlled_ids=["atk"])
    assert atk.stance == Stance.LOCK_ON
```

> If `switch_stance` refuses because of `stance_cooldown_remaining`, these
> freshly-built ships start at cooldown 0, so the switch is allowed. If the
> hulk's best weapon range is < 3 GU, move the enemy closer so it is "within
> best range" for the lock-on test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_fleet_pilot.py -k "braces or locks_on" -v`
Expected: FAIL — stance stays `Stance.STANDARD` (`_manage_stance` is a no-op).

- [ ] **Step 3: Implement `_manage_stance`**

First add the `Stance` import near the top of the file:

```python
from spacefleet.core.types import Stance
```

Then replace the `_manage_stance` stub with:

```python
    def _manage_stance(self, ship: Ship, target: Ship) -> None:
        if ship.stance_cooldown_remaining > 0:
            return
        crippled = ship.hull_current < BRACE_HULL_FRACTION * ship.hull.hull_hits
        if crippled:
            if ship.stance != Stance.BRACE_FOR_IMPACT:
                ship.switch_stance(Stance.BRACE_FOR_IMPACT)
            return
        best_range = max(w.weapon.range for w in ship.weapons)
        in_range = distance(ship.position, target.position) <= best_range
        if in_range and ship.stance != Stance.LOCK_ON:
            ship.switch_stance(Stance.LOCK_ON)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_fleet_pilot.py -q`
Expected: PASS (all unit tests).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src
git add src/spacefleet/net/ai_controller.py tests/test_ai_fleet_pilot.py
git commit -m "feat(ai): brace when crippled, lock on when engaging"
```

---

## Task 6: Integration smoke — an AI fleet fights to progress

**Files:**
- Test: `tests/test_ai_fleet_pilot.py`

- [ ] **Step 1: Write the failing test**

```python
def test_ai_fleet_drives_battle_forward() -> None:
    from spacefleet.net.turn_resolver import resolve_turn

    state = GameState.create_mixed(["imp"], ["cha"], ships_per_player=2, seed=7)
    ai = AIController()
    imp_ids = list(state.player_ships["imp"])
    cha_ids = list(state.player_ships["cha"])

    # Record starting separation between the two fleets' flagships.
    def _sep() -> float:
        from spacefleet.spatial.geometry import distance as d

        return d(state.ships[imp_ids[0]].position, state.ships[cha_ids[0]].position)

    start_sep = _sep()

    # Both fleets driven by the AI for several turns.
    for _ in range(12):
        cmds = {}
        cmds.update(ai.generate_commands(state, controlled_ids=imp_ids))
        cmds.update(ai.generate_commands(state, controlled_ids=cha_ids))
        resolve_turn(state, cmds)

    # The fleets closed distance (maneuver works) ...
    assert _sep() < start_sep
    # ... and combat happened: someone took hull damage or died.
    damaged = any(
        s.hull_current < s.hull.hull_hits or not s.alive
        for s in state.ships.values()
        if s.id in imp_ids + cha_ids
    )
    assert damaged
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run pytest tests/test_ai_fleet_pilot.py::test_ai_fleet_drives_battle_forward -v`
Expected: PASS once Tasks 1–5 are in. If it FAILS on "closed distance", the
fleets may start already within engage range and immediately trade fire without
closing — in that case assert `_sep()` is non-increasing (`<= start_sep`) and
rely on the `damaged` assertion for combat progress. If it FAILS on "damaged",
increase the loop to 20 turns (ranged closing may take longer at low speed).

- [ ] **Step 3: Gate + commit**

```bash
uv run ruff format src tests && uv run ruff check src tests && uv run mypy --strict src
uv run pytest -q
git add tests/test_ai_fleet_pilot.py
git commit -m "test(ai): AI-vs-AI fleet battle progresses (integration smoke)"
```

---

## Task 7: Final regression gate

- [ ] **Step 1: Full gate**

Run:
```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest -q
```
Expected: all clean; the full suite (235 prior + new AI tests) green. `game_room`
hulk behavior unchanged (default `controlled_ids=state.ai_ships`).

- [ ] **Step 2: No commit** — verification only. If any gap, add a follow-up task, fix, re-run.
