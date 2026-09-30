---
sidebar_position: 2
title: Turn Structure
---

# Turn Structure

Spacefleet Combat uses **simultaneous resolution**. Every player (and the AI) gives orders to all of their ships in secret. Once everyone has confirmed, the whole turn resolves for all sides at once.

Each ship gets a **free maneuver** plus **one action** per turn. Firing and moving are no longer mutually exclusive: a ship can change speed, turn, and fire in the same turn.

## Orders per Ship

| Order | Cost | Detail |
|---|---|---|
| Maneuver | Free | Target speed and a turn in degrees for this turn |
| Action | One per turn | **Fire**, **Boarding strike**, or **Pass** |
| Stance switch | Free | Change stance (Lock On, Brace for Impact, etc.), as before |

If the maneuver is left untouched, the ship keeps its current speed and does not turn.

### Maneuver

| Field | Meaning |
|---|---|
| Speed | Target speed for this turn. The ship moves `speed` GU in total over the turn |
| Turn | Degrees to port or starboard, executed **this turn only** |

| Rule | Detail |
|---|---|
| Turn limit (moving) | Up to the ship's turn rate |
| Turn limit (stationary) | A ship with speed 0 after the order pivots in place at **1.2×** its turn rate |
| No carry-over | Turns never persist into the next turn. Whatever you order is fully executed by end of turn |

### Actions

- **Fire** — Fire selected weapon(s) at a target. Arc and range are checked from the ship's position at the start of the turn.
- **Boarding strike** — Launch a boarding strike against a target.
- **Pass** — No action. The ship still executes its maneuver.

## Turn Timeline

Once all orders are in, the turn resolves on a single timeline shared by every ship.

| Time | Step | Detail |
|---|---|---|
| t = 0 | Commander abilities | Abilities resolve first, so buffs apply this turn |
| t = 0 | Fire | All fire resolves from **current positions**. Lances hit instantly; battery and torpedo salvos spawn and start travelling |
| t = 0 | Boarding strikes | Resolve after fire |
| t = 0 → 0.5 | Movement, first half | New speed and turn applied. Ships and salvos move together; half the turn is executed |
| t = 0.5 → 1 | Movement, second half | Ships and salvos keep moving; the other half of the turn is executed |
| t = 1 | End-of-turn effects | Shield regeneration, fire damage, morale checks |

Over the two halves a ship travels its full `speed` in GU, and its turn is split evenly: half the ordered degrees in each half, producing a curved path when the ship is moving.

## Continuous Collision

Salvos are not checked against a ship's final position. During each movement half, ships and salvos move **simultaneously**, and a salvo hits if its path passes within the **hit radius (2 GU)** of the moving ship at any moment.

| Rule | Detail |
|---|---|
| Hit test | A salvo hits when its distance to the moving ship drops to 2 GU or less |
| Range | A salvo only hits while still within its weapon's maximum range |
| Ordering | Impacts in a half resolve in time order |
| Destroyed ships | A ship destroyed by an earlier impact takes no later hits |
| Spent salvos | A salvo that hits is removed |

This means a ship can cross a salvo's path mid-turn and be hit, or arrive at the point only after the salvo has already passed and be missed.

## Lead Aiming

Because salvos travel, fire control aims ahead of the target. It computes an **exact intercept**: the point where a salvo fired now meets the target, assuming the target **holds its current course and speed**. A target that turns or changes speed after the orders are given can dodge the salvo.

## Turn Flow Diagram

```
┌──────────────────────────────┐
│   ORDERS (all players, AI)   │ ← Secret: maneuver + 1 action
│                              │   per ship, free stance switch
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   t=0  COMMANDER ABILITIES   │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   t=0  FIRE                  │ ← From current positions. Lances
│                              │   instant; salvos spawn
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   t=0  BOARDING STRIKES      │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   MOVEMENT (1st half)        │ ← Ships + salvos move together,
│                              │   continuous collision
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   MOVEMENT (2nd half)        │ ← Ships + salvos move together,
│                              │   continuous collision
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   END-OF-TURN EFFECTS        │ ← Shields, fires, morale
└──────────────┬───────────────┘
               ▼
           Next Turn
```

## Player Interaction per Turn

| Step | Player Actions | Time Pressure |
|------|---------------|---------------|
| Orders | Set maneuver, pick one action, optionally switch stance, for each ship | None — take your time |
| Resolution | Watch the turn play out for all sides | None |
| End of Turn | Read results, assess situation | None |

Every order is given with a full status readout. There is no time pressure — this is a game of tactical thinking, not reflexes. Because everyone commits before anything resolves, you must anticipate where the enemy will be, not react to where it went.

## Comparison with Previous System

| Previous (2 actions, sequential) | Current (maneuver + 1 action, simultaneous) |
|---|---|
| Up to 2 actions per turn; moving, turning, and firing competed for them | Free maneuver plus one action: moving never prevents firing |
| Actions resolved one after the other, with drift in between | All orders resolve at once on a shared timeline |
| Incomplete turns persisted into later turns | Turns execute fully within the turn; nothing carries over |
| Salvos checked against a ship's final position | Continuous collision: ships and salvos move simultaneously |
| Lead aiming approximated in discrete steps | Exact intercept against targets holding course |
