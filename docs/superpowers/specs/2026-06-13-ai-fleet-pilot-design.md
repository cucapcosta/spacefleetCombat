# AI Fleet Pilot — Design Spec

**Date:** 2026-06-13
**Status:** Approved
**Sub-project:** 1 of 3 (AI → Fleet Builder → Campaign Gauntlet)

## Goal

Upgrade the battle AI from the current hulk-only, fire-or-pass behaviour into a
policy that can pilot a full enemy **fleet** — maneuver toward the player, fire
when a solution exists, and manage combat stance. This makes solo PvE battles a
real fight, which the campaign gauntlet (sub-project 3) depends on.

Out of scope (deferred): commander active abilities, formation/coordination
between AI ships, pathfinding around terrain, threat-weighted fleet strategy.
These belong to the larger Sprint 7 `ai/` package; this spec keeps the AI in
`net/ai_controller.py` where it is already wired into `game_room`.

## Engine constraints (must respect)

- Each alive ship submits **exactly one** `Command` per turn:
  `fire | ahead | stop | turn | pass`. A ship therefore either shoots *or*
  maneuvers in a given turn, never both.
- Stance switching is **free** — applied directly on the ship (e.g.
  `ship.switch_stance(...)`), not via a `Command`, so it does not consume the
  ship's action. Respect `ship.stance_cooldown_remaining`.
- `Command(action="fire", args={"slot": int, "bearing": float})`.
- `Command(action="turn", args={"direction": "port"|"starboard", "degrees": float})`.
- `Command(action="ahead", args={"speed": float})`. `Command(action="stop")`.
- Targeting helpers available: `state.enemy_ships_of(ship)`,
  `bearing_from_to(a, b)`, `distance(a, b)`, `is_in_arc(heading, bearing, arc)`.

## Interface

```python
class AIController:
    def __init__(self, fire_chance: float = 1.0) -> None: ...

    def generate_commands(
        self,
        state: GameState,
        controlled_ids: list[str] | None = None,
    ) -> dict[str, Command]:
        """One Command per alive controlled ship.

        controlled_ids defaults to ``state.ai_ships`` (current hulk behaviour);
        the campaign passes an explicit enemy-fleet ship-id list.
        Stance changes are applied as a side effect before the Command is built.
        """
```

`game_room` keeps calling `self.ai.generate_commands(self.state)` unchanged
(default arg preserves today's hulk behaviour).

`fire_chance` is retained as a tunable (default raised to `1.0` so the fleet AI
fires whenever it has a solution; hulk scenarios can lower it for flavour).

## Per-ship decision policy

For each alive controlled ship, in order:

1. **No weapons or no enemies** → `pass`.
2. **Stance management (free, before choosing the action):**
   - If `hull_current < 0.4 * hull.hull_hits` and stance is not Brace and
     cooldown is 0 → switch to **Brace** (survive while damaged).
   - Else if the nearest enemy is within the ship's best weapon range, stance is
     not Lock On, and cooldown is 0 → switch to **Lock On** (improve accuracy as
     it engages). Brace takes precedence over Lock On.
3. **Choose a target:** the **nearest** alive enemy by distance. Tie-break by
   `ship.id` for determinism. Among enemies that are *in a firing solution*
   (in-arc and in-range of some weapon), prefer one whose `shields_current == 0`
   (finishing/penetrating priority); otherwise nearest.
4. **Fire** if a firing solution exists against the chosen target: pick the
   weapon that bears on the target (in-arc + in-range) with the highest
   `weapon.strength`; emit `fire` with that weapon's `slot_id` and the bearing to
   the target. Gated by `fire_chance` (default 1.0 → always when a solution
   exists).
5. **Maneuver** when there is no firing solution:
   - If the target is **outside a fixed ±45° prow cone** of the ship's heading →
     `turn` toward the target's bearing. Direction = shortest angular side;
     `degrees` = min(angular delta, ship's max turn for the turn). (The prow cone,
     not the weapon arcs, decides "nose roughly at the enemy": broadside ships
     cover ~360° of arc, so an arc-based test would never turn them and they would
     never close. Firing still uses the real per-weapon arcs.)
   - Else if the target is **too far** (distance > preferred engagement range,
     defined as `0.6 * best_weapon_range`) → `ahead` toward a speed that closes
     distance, capped at `ship.effective_speed_max` (and never below current
     drift needs). Use a simple target speed = the cap.
   - Else (in range band but no current arc/solution, e.g. just turned) →
     `stop` to settle and re-evaluate next turn.

The policy is intentionally greedy and per-ship; emergent fleet behaviour
(several ships converging on the player) arises from each independently chasing
the nearest enemy. No cross-ship coordination in v1.

## Determinism

All randomness flows through `state.dice` (e.g. the `fire_chance` roll). Given a
fixed seed and state, command generation is reproducible. Turn/ahead/fire
geometry is pure.

## Testing

`tests/test_ai_fleet_pilot.py`:

- **fire-in-solution:** enemy placed in-arc and in-range → returns a `fire`
  Command targeting the correct slot and bearing.
- **turn-to-face:** enemy in range but outside arc → returns a `turn` toward the
  enemy's side (correct `direction`).
- **close-distance:** enemy far and roughly ahead → returns an `ahead` Command
  with speed > 0.
- **brace-when-crippled:** ship at <40% hull → stance becomes Brace; Command may
  be anything but stance side-effect asserted.
- **lock-on-when-engaging:** healthy ship with enemy in range → stance becomes
  Lock On.
- **shields-down preference:** two enemies in solution, one with shields 0 →
  fires at the unshielded one.
- **controlled_ids respected:** only ships in the passed set get Commands;
  default falls back to `state.ai_ships`.
- **integration smoke:** build a `create_mixed` battle, drive both fleets with
  the AI for N turns via `resolve_turn`, assert the flagships **close distance**
  (maneuver works) and at least one `SalvoImpactEvent` resolves (live fire). It
  does **not** assert fleet-on-fleet hull damage — see the limitation below.

## Known limitation: greedy fire has no projectile lead

Battery weapons fire slow projectiles aimed at the target's bearing **at launch**;
against a maneuvering enemy fleet those salvos usually miss (they mostly strike
stationary neutral hulks that wander into the line of fire). The v1 AI is
deliberately greedy and does **not** lead its shots, so AI-vs-AI fleet battles can
fail to produce casualties unless ships close to near-point-blank range. This is an
accepted v1 limitation (decided with the user). Consequence for downstream work:
the **campaign gauntlet (sub-project 3) must impose a turn limit / explicit victory
condition** rather than relying on a fleet being wiped out. Adding intercept-lead
fire control is a deferred future enhancement.

## Quality gate

`uv run ruff check src tests && uv run ruff format --check src tests &&
uv run mypy --strict src && uv run pytest -q`. All currently-green tests stay
green; `game_room` behaviour for existing hulk scenarios is unchanged by the
default argument.
