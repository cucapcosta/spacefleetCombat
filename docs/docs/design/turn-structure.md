---
sidebar_position: 2
title: Turn Structure
---

# Turn Structure

Spacefleet Combat uses an **action-based turn system** where each turn the player selects **up to 2 actions** that resolve sequentially on a continuous timeline, with time flowing between them.

This replaces the old 5-phase system (Command, Movement, Shooting, Ordnance, End). Instead of locking decisions into separate phases, you freely combine actions in any order, creating meaningful tactical choices about sequencing. The old "special orders" mechanic and phase-locked resolution are fully removed.

## How It Works

Each turn follows this sequence:

1. **View status** — Player sees current position, heading, speed, and contacts.
2. **Select Action 1** (or pass).
3. **Action 1 resolves** instantly from the ship's current position and state.
4. **Time flows (first half)** — Ship moves for half the turn duration based on current speed and heading. All other ships also drift.
5. **Select Action 2** (or pass).
6. **Action 2 resolves** from the ship's **new position** (after the first-half drift).
7. **Time flows (second half)** — Ship moves for the remaining half of the turn.
8. **End-of-turn effects** — Shield regeneration, fire damage, morale checks, sensor updates.

## Key Insight: Action Order Matters

Because time flows between your two actions, the order you choose them in changes the outcome:

- **Shoot then Move**: The shot fires from your original position, then your ship starts moving away.
- **Move then Shoot**: Your ship drifts halfway first, then the shot fires from the new position.

This creates meaningful tactical decisions about action sequencing. Do you fire from a safe distance then close in? Or rush forward to get a better angle before shooting?

## Available Actions

These count toward your 2-action limit per turn:

- **Shoot** — Fire selected weapon(s) at a target. The target must be within weapon arc and range from the ship's current position at the moment the action resolves.
- **Move Ahead** — Set speed to cruising speed. The ship begins or continues forward movement.
- **Stop** — Begin decelerating to zero speed.
- **Turn** — Order a heading change of up to `turn_rate` degrees (port or starboard). The rotation executes **gradually during drift**, producing a curved arc when the ship is moving. While stationary, the ship **pivots in place** at 120% of normal turn rate (faster, but the ship is an easy target). Incomplete turns persist across turns until fully resolved — the player can cancel or replace them with a new turn order.
- **Pass** — Do nothing. The ship continues drifting at its current speed and heading.

## Free Actions

These do **not** count as one of your 2 actions. You can use them at any point during your turn:

- **Scan** — View sensor contacts and their estimated positions.
- **Status** — View detailed ship and fleet status.
- **Stance Switch** — Change between stances (Lock On, Brace for Impact, etc.). Stances are now free actions rather than requiring a special order and leadership check as in the old phase system.

## Time Flow Model

Each turn represents a fixed time window. Ship movement per turn equals the ship's speed in GU (Grid Units) per turn.

- **Between Action 1 and Action 2**: ship moves `speed x 0.5` GU along its current heading.
- **After Action 2**: ship moves `speed x 0.5` GU along its current heading.
- **Total movement per turn** = `speed` GU, split evenly across the two halves.

All other ships in the engagement follow the same time model — they drift during both half-turn intervals based on their own speed and heading.

## Turn Flow Diagram

```
┌──────────────────────────┐
│     VIEW STATUS          │ ← Position, heading, speed, contacts
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│   SELECT ACTION 1        │ ← Shoot, Move, Turn, Stop, or Pass
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│   ACTION 1 RESOLVES      │ ← Instant, from current position
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│   TIME FLOWS (1st half)  │ ← All ships drift: speed × 0.5 GU
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│   SELECT ACTION 2        │ ← Shoot, Move, Turn, Stop, or Pass
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│   ACTION 2 RESOLVES      │ ← Instant, from NEW position
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│   TIME FLOWS (2nd half)  │ ← All ships drift: speed × 0.5 GU
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│   END-OF-TURN EFFECTS    │ ← Shield regen, fire damage,
│                          │   morale checks, sensor updates
└────────────┬─────────────┘
             ▼
         Next Turn
```

## Player Interaction per Turn

| Step | Player Actions | Time Pressure |
|------|---------------|---------------|
| View Status | Review ship state and contacts | None — take your time |
| Action 1 | Choose any action (or pass) | None |
| Action 2 | Choose any action (or pass) | None |
| End of Turn | Read results, assess situation | None |

Every step gives you a full status readout before asking for decisions. There is no time pressure — this is a game of tactical thinking, not reflexes. With only 2 decision points per turn (down from 5 phases), each choice carries more weight.

## Multiplayer Resolution (Future)

When the game becomes multiplayer, the action-based system extends to simultaneous resolution:

1. All players **simultaneously** select their 2 actions (hidden from each other).
2. Once all players confirm, actions resolve simultaneously with time progression:
   - **t=0** — Action 1 for ALL players resolves.
   - **t=0 to t=0.5** — Time flows (first half turn). All ships drift.
   - **t=0.5** — Action 2 for ALL players resolves.
   - **t=0.5 to t=1** — Time flows (second half turn). All ships drift.
3. End-of-turn effects apply to all ships.
4. A central server handles all calculations to prevent cheating.

This creates simultaneous resolution that preserves the "plan and pray" tension of the old phase system while giving players the flexibility of action-based decision-making.

## Comparison with Old Phase System

| Old (5-Phase) | New (Action-Based) |
|---|---|
| Separate Command, Movement, Shooting, Ordnance, End phases | 2 actions per turn, any mix |
| Special orders required leadership checks | Stances are free actions, no checks needed |
| Movement and shooting in different phases | Can shoot and move in any order |
| All movement happens at once | Movement is interleaved with actions |
| Position doesn't change during shooting | Position changes between actions |
| 5 decision points per turn | 2 decision points (simpler) |
| Phase-locked decisions | Flexible action combinations |
