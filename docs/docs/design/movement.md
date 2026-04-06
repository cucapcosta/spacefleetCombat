---
sidebar_position: 6
title: Movement
---

# Movement System

Ships move on a 2D plane with facing. Movement is governed by speed, turn rate, and a **combustion gauge** that limits boosting — inspired by BFG Armada's engine management.

## Coordinate System

- **2D Cartesian plane** with floating-point coordinates (x, y) in game units (GU).
- **Heading**: 0-360°. 0° = north (positive Y), 90° = east, clockwise.
- **Battlefield**: Bounded rectangle, typically 240 × 180 GU.

## Combustion Gauge

Each ship has a **combustion gauge** (0-100) that represents engine fuel reserves for boosting:

- **Regeneration**: +15 per turn at cruising speed (not boosting)
- **Boost cost**: Boosting (All Ahead Full) consumes 40 gauge per turn
- **High Energy Turn cost**: 25 gauge per sharp turn
- **At 0**: Cannot boost or high-energy turn until gauge recovers

This creates a resource management layer — you can't boost forever. Sprint to close distance, then cruise to recover, then sprint again.

```
Combustion Gauge: [████████████████░░░░] 80/100
```

## Movement Rules

### 1. Determine Effective Speed

```
effective_speed = base_speed
  × damage_modifier           # crippled = ×0.5, engines critical = ×0.5
  + boost_bonus                # All Ahead Full: +2D6 (costs gauge)
  - blast_marker_penalty       # -5 per blast marker nearby
```

### 2. Minimum Advance

Before turning, the ship must advance at least `turn_delay` GU straight ahead.

| Ship Class | Typical Turn Delay |
|-----------|-------------------|
| Escort | 5 GU |
| Cruiser | 10 GU |
| Battleship | 15 GU |

### 3. Standard Turn

After minimum advance, rotate up to `turn_rate` degrees. Multiple turns possible if enough movement remains (each requires another `turn_delay`).

### 4. High Energy Turn (New)

A sharp, aggressive maneuver that burns the combustion gauge:

- Turn up to **90°** at any point, ignoring `turn_delay`
- Costs **25 combustion gauge**
- Reduces remaining movement by **half**
- Cannot be used if combustion gauge is below 25

### 5. Boost (All Ahead Full)

Maximum engine output:

- Speed increased by **2D6** GU this turn
- Costs **40 combustion gauge**
- Ship **cannot fire weapons** this turn
- Ship **cannot turn** during the boost (straight line only)

### 6. Burn Retros (Emergency Stop)

- Ship decelerates to **quarter speed** this turn
- May make **additional turns** beyond normal limit
- No combustion gauge cost
- Useful for sharp repositioning at the cost of distance

## Movement Orders

| Command | Description |
|---------|-------------|
| `move ahead` | Full speed, no turn |
| `move turn port 30` | Turn 30° left during movement |
| `move turn starboard 45` | Turn 45° right |
| `move to 50 80` | Auto-plot course toward coordinates |
| `speed 15` | Set desired speed (up to max) |
| `boost` | All Ahead Full (+2D6 speed, no weapons, no turning) |
| `high_energy_turn port 60` | Sharp 60° left turn (costs gauge) |

## Collision / Ramming

If two ships end movement within threshold distance:

- Both ships take damage based on relative speed and hull
- **Power Ram** upgrade: +50% ram damage dealt
- Larger ship deals more damage
- Intentional ramming is a valid (desperate) tactic for escorts against capital ships

## Movement Example

```
ISS Hammer of Light (Lunar Cruiser)
  Position: (50.0, 40.0)  Heading: 000°
  Speed: 20  Turn Rate: 45°  Turn Delay: 10
  Combustion: 65/100

[MOVEMENT]> move turn starboard 30

  Step 1: Advance 10 GU along heading 000°
    → (50.0, 50.0)
  Step 2: Turn 30° starboard
    → Heading: 030°
  Step 3: Advance 10 GU along heading 030°
    → (55.0, 58.7)

  Final: Position (55.0, 58.7), Heading 030°
  Combustion: 65/100 (no boost used → +15 regen next turn)

---

[MOVEMENT]> boost

  All Ahead Full! Rolling 2D6: 8
  Total movement: 20 + 8 = 28 GU straight ahead.
  → (50.0, 68.0)  Heading: 000° (no turning allowed)
  Combustion: 65 - 40 = 25/100
  WARNING: Cannot fire weapons this turn.
```
