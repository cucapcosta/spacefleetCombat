---
sidebar_position: 2
title: Weapon Types
---

# Weapon Types Reference

## Weapons Battery

**Macro-cannons and ballistic weapons fired in massive broadsides.**

| Property | Value |
|----------|-------|
| Hit Mechanic | Gunnery Table |
| Ignores Shields | No |
| Ignores Armor | No |
| Can Crit | Yes |

### How It Works
1. Count the weapon's **strength** (firepower dice)
2. Determine **target aspect** (closing, abeam, running) for column selection
3. Apply modifiers (range, Lock On order)
4. Consult the gunnery table for number of hits
5. Each hit is absorbed by shields → armor save → hull damage

### Strengths
- High volume of fire
- Very effective at close range against broadside targets
- Good against lightly armored escorts

### Weaknesses
- Less effective at long range (firepower halved)
- Less effective against closing targets (column shift)
- Stopped by armor saves

---

## Lance

**Focused energy beams that cut through armor.**

| Property | Value |
|----------|-------|
| Hit Mechanic | Flat Roll (4+ on D6) |
| Ignores Shields | No |
| Ignores Armor | **Yes** |
| Can Crit | Yes |

### How It Works
1. Roll **1D6 per strength point**
2. Each roll of **4+** is a hit
3. Hits are absorbed by shields first
4. Any hit passing shields goes **straight to hull** (no armor save)
5. Lock On order allows re-rolling misses

### Strengths
- Ignores armor entirely — devastating against heavily armored ships
- Consistent hit rate (50%) regardless of target aspect
- Long range on many platforms

### Weaknesses
- Lower volume of fire than batteries
- Still blocked by shields
- Expensive in points

---

## Torpedo

**Self-guided munitions launched in salvos.**

| Property | Value |
|----------|-------|
| Hit Mechanic | Ordnance (travel + impact) |
| Ignores Shields | **Yes** |
| Ignores Armor | No |
| Can Crit | Yes |
| Interceptable | Yes (by turrets) |

### How It Works
1. **Launch**: Salvo of torpedoes launched on a heading during Shooting Phase
2. **Travel**: Torpedoes move at their speed each Ordnance Phase
3. **Intercept**: Target's turrets destroy 1 torpedo each
4. **Impact**: Remaining torpedoes roll 4+ to hit, each dealing 1 hull damage
5. Torpedoes bypass shields entirely

### Strengths
- Bypass shields — direct hull damage
- Devastating in large salvos
- Can be aimed at a heading (area denial)

### Weaknesses
- Travel time — enemy can dodge
- Intercepted by turrets
- Limited stock (must Reload Ordnance)
- Travel in straight lines (no tracking)

---

## Nova Cannon

**Massive spinal-mount weapon with area-of-effect damage.**

| Property | Value |
|----------|-------|
| Hit Mechanic | Scatter (deviation from target point) |
| Ignores Shields | **Yes** |
| Ignores Armor | No |
| Can Crit | Yes |
| Creates Blast Markers | Yes |

### How It Works
1. Nominate a **target point** within range
2. Shell deviates **2D6 GU** in a random direction
3. All ships within the **blast radius** take **D6 hits**
4. Creates a blast marker at detonation point
5. Bypasses shields

### Strengths
- Extreme range (100 GU)
- Area of effect — can hit multiple ships
- Bypasses shields
- Creates blast markers (slows and disrupts enemies)

### Weaknesses
- Very inaccurate (2D6 scatter)
- Only 1 strength (one shot per turn)
- Rare — only on select battlecruiser/battleship platforms
- Can scatter onto friendly ships
