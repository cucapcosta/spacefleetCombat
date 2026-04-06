---
sidebar_position: 5
title: Combat
---

# Combat System

Combat is resolved during the **Shooting Phase** (direct fire) and the **Ordnance Phase** (torpedoes). All fire is simultaneous — a ship destroyed this turn still fires.

## Weapon Arcs

Every weapon slot has a **firing arc** — an angular sector relative to the ship's heading.

```
              000° (Prow)
               /|\
              / | \
     315°   /  |  \   045°
            /   |   \
    PORT   / PROW \  STARBOARD
   270° ---|   ■   |--- 090°
            \     /
             \   /
              \ /
              225° (Aft) ... 135°
```

| Arc | Angular Range | Description |
|-----|--------------|-------------|
| **Prow** | -45° to +45° | Forward 90° |
| **Port** | +45° to +135° | Left broadside 90° |
| **Starboard** | -135° to -45° | Right broadside 90° |
| **Dorsal** | -135° to +135° | Everything except stern (270°) |
| **Aft** | +135° to +225° | Rear 90° |

## Weapon Battery Resolution

Weapon batteries (macro-cannons) use the **gunnery table**:

### Step 1: Check Arc and Range
- Is the target within the weapon's firing arc?
- Is the target within maximum range?
- Beyond 50% of max range → halve firepower (round up)

### Step 2: Determine Target Aspect
- **Closing** (target showing prow): Column shift LEFT (harder)
- **Abeam** (target showing broadside): Standard — no shift
- **Running** (target showing stern): Column shift RIGHT (easier)

### Step 3: Apply Modifiers
- **Lock On** stance: +1 column shift RIGHT
- **Reload** stance: -1 column shift LEFT (accuracy penalty)
- **Concentrated Fire** ability: +1 column shift RIGHT
- **Armour-Piercing Ammo** upgrade: Ignore 1 armor at close range

### Step 4: Consult Gunnery Table
Cross-reference effective firepower with final column → number of hits.

### Step 5: Apply Hits
1. **Shields** absorb hits one-for-one
2. **Armor save** per remaining hit (D6 ≥ armor value for facing = **penetrates**; higher armor value = harder to penetrate = stronger)
3. Each penetrating hit → **1 hull damage**
4. Each penetrating hit → **critical hit check** (2D6, modified by stance)

## Lance Resolution

Lances are precision energy weapons:

1. Roll **1D6 per strength**
2. **4+** = hit (3+ with Mark of Tzeentch doctrine or Lance Mastery passive)
3. Hits **bypass armor saves** — damage goes through shields to hull
4. **Lock On** stance: re-roll misses
5. **Disruption Lance** upgrade: +25% critical chance

## Torpedo Resolution

Torpedoes are independent ordnance (see [Movement](movement) for travel):

### Impact
1. **Turrets** intercept: each turret destroys 1 torpedo
2. Remaining torpedoes roll **4+** to hit
3. Each hit deals **1 hull damage, bypassing shields**
4. **Melta Torpedoes**: +1 damage per hit, ignore armor
5. **Boarding Torpedoes**: Deliver assault actions instead of damage

### Properties
- Bypass shields entirely
- Interceptable by turrets
- Travel in straight lines (no tracking)
- Limited stock — must use **Reload Ordnance** to restock

## Nova Cannon

Massive spinal-mount weapon:

1. Nominate a **target point** within range (100 GU)
2. Shell deviates **2D6 GU** in random direction
3. All ships within **blast radius** take **D6 hits**
4. Creates a **blast marker** at detonation
5. Bypasses shields

## Subsystem Targeting

When firing, you can optionally **target a specific subsystem** on a capital ship:

```
[SHOOTING]> target subsystem engines on defiler
```

- **Accuracy penalty**: -1 column shift LEFT on gunnery table (harder to hit precisely)
- **If a hit penetrates**: Instead of rolling on the random critical table, the critical damage is applied directly to the targeted subsystem
- **Escorts**: Cannot be subsystem-targeted (too small)

### Subsystem Effects

| Subsystem | When Critically Damaged |
|-----------|------------------------|
| **Generator** | Shields collapse to 0, cannot regenerate |
| **Deck** | Cannot switch stances, -20 morale |
| **Engines** | Speed halved, cannot boost or high-energy turn |
| **Weapons** | All weapons disabled |

## Shield Mechanics

- Each shield absorbs **one hit** (from batteries or lances)
- Shields regenerate **1 per End Phase** (up to max)
- **Auxiliary Shield Capacitor** upgrade: +1 regen
- **Generator critical**: Shields collapse, no regen
- Torpedoes and nova cannon **bypass shields**
- **Brace for Impact** stance: Adds extra armor save (6+) to hits that pass shields

## Critical Hits

When a hit penetrates armor, roll **2D6** on the critical hit table:

| 2D6 | Critical Hit | Effect |
|-----|-------------|--------|
| 2 | Shields Collapsed | Shields drop to 0 for 1 turn |
| 3 | Thrusters Damaged | Ship cannot turn |
| 4 | Armament Damaged | Random weapon slot disabled |
| 5 | Prow Armament Damaged | All prow weapons disabled |
| 6 | Engine Room Damaged | Speed halved |
| 7 | Hull Breach | +1 extra hull damage |
| 8 | Engine Room Damaged | Speed halved |
| 9 | Fire! | 1 hull damage per turn until extinguished |
| 10 | Bulkhead Collapse | D3 extra hull damage |
| 11 | Bridge Destroyed | Leadership -3 |
| 12 | Magazine Detonation! | D6 extra damage (+D6 if carrying torpedoes) |

**Lock On** stance: +25% critical chance (re-roll results of 7 "Hull Breach" once, keeping the new result).

## Boarding Actions

Close-range crew combat (see [Morale & Crew](morale-and-crew) for full details):

1. Must be within **5 GU** (or 15 GU with Lightning Strike ability)
2. Deliver **assault actions** based on ship class
3. Each assault can damage crew, hit subsystems, or be repelled
4. Boarding through active shields: -1 to assault rolls
5. Morale damage from boarding can push ships toward mutiny

## Morale in Combat

Ships have a morale value (0-100+) that fluctuates during battle:

- **Drops** from: hull damage, nearby allies destroyed, boarding, fire
- **Recovers** from: Call to Arms ability, destroying enemies, End Phase
- **At 0 morale**: Ship enters **MUTINY** (cannot fight, flees)
- See [Morale & Crew](morale-and-crew) for the full system

## Damage Example

```
ISS Hammer of Light fires Port Macro-Cannon Mk.III (str 6)
  Target: "Defiler" (Murder Cruiser)
  Stance: Lock On (+1 column right)

  Target aspect: ABEAM (broadside exposed)
  Range: 38 GU (within 45 max — full firepower)
  Gunnery column: Abeam + Lock On → Running column

  Gunnery table: str 6, running → 3 hits

  Shield absorption: Defiler has 1 shield → absorbs 1 hit
  Remaining hits: 2

  Armor saves (facing: port, armor 5 — need D6 ≥ 5 to penetrate):
    Hit 1: roll 4 → 4 < 5, deflected
    Hit 2: roll 6 → 6 ≥ 5, PENETRATES → 1 hull damage

  Hull damage: 1 → Defiler now at 7/10 hull
  Morale: 72 → 69 (-3 from hull damage)

  Critical hit (Lock On bonus active): 2D6 = 7 → Hull Breach
    Lock On re-roll: 2D6 = 9 → FIRE! (kept — worse for the enemy)
    +1 hull damage from fire per turn
    Morale: 69 → 64 (-5 from critical)
```
