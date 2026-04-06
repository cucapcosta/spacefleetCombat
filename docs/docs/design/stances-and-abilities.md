---
sidebar_position: 7
title: Stances & Abilities
---

# Stances and Abilities

The original Battlefleet Gothic tabletop used "special orders" that required leadership checks each turn. BFG Armada replaced this with a two-tier system: **stances** (persistent ship states) and **active abilities** (commander-driven actions from the flagship). Spacefleet Combat uses this same approach.

## Stances

Stances are **persistent operational modes** for each ship. A ship is always in exactly one stance. Switching stances has a **cooldown** — you can't flip between them every turn.

### Switching Stances
- Ships start each battle in **Standard** stance
- Switching to a new stance takes effect **immediately**
- After switching, there is a **2-turn cooldown** before switching again
- No leadership check required — stances are reliable

### Available Stances

#### Standard
- **Effect**: No bonuses, no penalties. Baseline operation.
- **Use case**: Default. Use when you don't need a specific stance.

#### Lock On
- **Effect**:
  - Weapon batteries: +1 column shift right on the gunnery table
  - Lances: re-roll missed dice (one re-roll per die)
  - +25% critical hit chance on all weapons
- **Drawback**: None
- **Use case**: Maximum firepower. The go-to offensive stance when in weapons range.

#### Brace for Impact
- **Effect**:
  - All incoming weapon hits get an additional armor save (6+ on D6)
  - -25% hull damage from all sources
  - +50% turret accuracy against torpedoes
- **Drawback**: All weapon strengths **halved** (round up)
- **Use case**: Surviving heavy incoming fire. Accept reduced damage output to stay alive.

#### Reload
- **Effect**:
  - +25% faster ability cooldown recovery (commander abilities on flagship)
  - Torpedo reload takes 1 fewer turn
  - +40% weapon battery fire rate (effectively +1 strength on all batteries)
- **Drawback**: -10% accuracy (shift left on gunnery table for batteries)
- **Use case**: Between engagements, while repositioning, or when you need abilities back quickly.

#### Running Silent
- **Effect**:
  - Ship's detection signature is reduced by **50%** (harder for enemies to detect)
  - Ship appears as a Blip even at Contact range
- **Drawback**:
  - Ship's own sensor range is **halved**
  - Cannot fire weapons (breaks silent running)
  - Firing weapons or using abilities immediately drops Running Silent
- **Use case**: Flanking maneuvers, sneaking torpedo boats into position, ambushes.

### Stance Summary Table

| Stance | Offense | Defense | Movement | Detection |
|--------|---------|---------|----------|-----------|
| **Standard** | — | — | — | — |
| **Lock On** | +++ | — | — | — |
| **Brace** | -- | +++ | — | — |
| **Reload** | + | — | — | — |
| **Running Silent** | Cannot fire | — | — | Stealth +++ |

## Active Abilities

Active abilities are **commander powers** usable only from the **flagship**. They have cooldowns (turns) and limited charges per battle. See the [Fleet Commander](fleet-commander) page for the full ability list.

### Using Abilities in Battle

```
[Turn 3 | ANY PHASE | ISS Hammer of Light (FLAGSHIP)]> ability emergency_repairs

  EMERGENCY REPAIRS activated!
  Hull restored: 6/8 → 7/8 (+1)
  Fires extinguished: 1 fire removed
  Charges remaining: 1/2
  Cooldown: 4 turns (available again turn 7)
```

### Ability Timing

- Abilities can be used **during any phase** (unless specified otherwise)
- Using an ability does **not** consume the ship's action for that phase
- Only **one ability per turn** from the flagship
- Abilities that affect other ships require **line of sight** or **range** as specified

### Ability vs. Stance Interaction

| Ability | Works in any stance? | Notes |
|---------|---------------------|-------|
| Micro Warp Jump | Yes | Preparation turn required |
| Emergency Repairs | Yes | — |
| Call to Arms | Yes | Range-based, affects nearby ships |
| Augur Probe | Yes | Deploy anywhere in sensor range |
| Concentrated Fire | Yes | Designate a target |
| Torpedo Barrage | No — not in Brace | Requires offensive posture |
| Boarding Assault | No — not in Running Silent | Must be visible |

## Comparison: Old Special Orders vs. New System

| Old System (Tabletop) | New System (Armada-Inspired) |
|-----------------------|---------------------------|
| Per-ship, per-turn orders | Stances persist until switched |
| Leadership check each turn (can fail) | No check needed — always works |
| Must choose: offense OR defense OR movement | Stances define posture; abilities add on top |
| Same for all ships | Abilities are flagship-only, creating flagship importance |
| No cooldowns | Stance switch cooldown + ability cooldowns |
| 6 orders available | 5 stances + many abilities = more options |

## Tactical Considerations

### Stance Coordination
- **Closing fleet**: Lock On as you approach weapons range, maximizing damage in the critical first exchange
- **Holding fleet**: Brace for Impact on ships absorbing fire, Lock On on ships behind cover
- **Flanking force**: Running Silent until in position, then switch to Lock On and open fire (2-turn cooldown means you commit to the ambush)

### Flagship Positioning
- Your flagship is the **only source of active abilities** — it needs to be where the action is
- But losing the flagship is **catastrophic** for morale and abilities
- Balancing flagship risk vs. ability access is a core strategic tension
- Some players put the commander on a battleship (tough but slow), others on a cruiser (mobile but fragile)

### Cooldown Management
- Ability cooldowns mean you can't spam Emergency Repairs — use them at the right moment
- Stance switch cooldowns mean you commit for at least 2 turns — choose wisely
- Reload stance recovers ability cooldowns faster — use it between engagements
