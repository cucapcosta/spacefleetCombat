---
sidebar_position: 6
title: Detection & Sensors
---

# Detection and Sensor System

One of the core design pillars of Spacefleet Combat is **information warfare**. You don't have perfect knowledge of the battlefield — you see what your sensors tell you, and sensors have limits.

## Sensor Ranges

Each ship class has a base detection range:

| Classification | Base Sensor Range |
|---------------|-------------------|
| Escort | 80 GU |
| Light Cruiser | 100 GU |
| Cruiser | 120 GU |
| Battlecruiser | 140 GU |
| Battleship | 160 GU |

Your fleet's effective sensor range is determined by your best sensor-equipped ship (usually the flagship or largest vessel).

## Detection Levels

Enemy contacts are classified by **detection confidence**, based on distance and conditions:

### Level 0 — Undetected
Beyond sensor range. You don't know they exist.

### Level 1 — Blip
At maximum sensor range. Provides only approximate information.

```
[BLIP] Unknown contact, bearing 045, ~120 GU
```

- Approximate bearing and range (±10 GU)
- No ship class or identity
- Could be one ship or several close together
- Cannot be targeted by weapons

### Level 2 — Contact
Within 75% of sensor range. Ship class is identified.

```
[CONTACT] Cruiser-class contact, bearing 045, range 87 GU
```

- Accurate bearing and range
- Ship classification (escort, cruiser, battleship, etc.)
- Number of ships in group
- Can be targeted by long-range weapons (with accuracy penalty)

### Level 3 — Identified
Within 50% of sensor range, or previously scanned at close range.

```
[IDENTIFIED] Murder-class Cruiser "Defiler", bearing 045, range 43 GU
  Hull: 6/10 | Shields: 1/2 | Speed: 25 | Heading: 200°
```

- Full ship profile visible (class, name, armament)
- Current hull, shields, and speed
- Heading and exact position
- Active special orders may be detectable
- Can be targeted normally

## Detection Modifiers

Several factors affect detection:

| Factor | Effect |
|--------|--------|
| **Blast markers near target** | Each blast marker near a ship provides -10 GU to detection range against it (harder to see through explosions) |
| **Running Silent** order | Ship's detection signature reduced by 50%, but own sensor range also halved |
| **Nebula** | Ships inside a nebula can only be detected within 30 GU |
| **Asteroid field** | Reduces detection range by 25% for contacts within the field |
| **Flagship sensor suite** | +20 GU to base sensor range |

## Scanning

The `scan` command provides detailed readouts:

### Fleet-wide scan
```
> scan

SENSOR READOUT — Turn 5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FRIENDLY FORCES:
  ISS Hammer of Light  (Lunar Cruiser)    Pos: (45, 83)  Hdg: 065°
  ISS Vigilant         (Sword Frigate)    Pos: (30, 55)  Hdg: 035°
  ISS Relentless       (Sword Frigate)    Pos: (33, 56)  Hdg: 035°

CONTACTS:
  [IDENTIFIED] "Defiler"   Murder Cruiser    Brg: 048  Rng: 47 GU  Hdg: 200°
  [CONTACT]    Cruiser-class                  Brg: 078  Rng: 91 GU
  [BLIP]       Unknown                        Brg: 120  Rng: ~130 GU
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Targeted scan
```
> scan defiler

TARGET SCAN — "Defiler" (Murder-class Cruiser)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Detection Level:  IDENTIFIED
  Position:         (61.3, 94.2)
  Bearing:          048° from ISS Hammer of Light
  Range:            47 GU
  Heading:          200° (heading roughly toward us)
  Speed:            25 GU/turn
  Closing Rate:     ~12 GU/turn

  Hull:             6/10 [██████░░░░]
  Shields:          0/2  [░░]
  Status:           FIRE (ongoing damage)

  Armament:
    Port Battery     (str 4, range 45)  — OPERATIONAL
    Stbd Battery     (str 4, range 45)  — OPERATIONAL
    Port Lances      (str 4, range 60)  — OPERATIONAL
    Stbd Lances      (str 4, range 60)  — DAMAGED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Tactical Implications

The detection system creates meaningful decisions:

1. **Approach angle matters**: Closing fast from outside detection range lets you choose the engagement terms
2. **Running Silent**: Useful for flanking forces — trade your own sensor data for stealth
3. **Escorts as scouts**: Fast escorts can push forward to identify contacts for the fleet
4. **Engagement range**: Fighting at long range means reduced sensor data — you might not see the flanking force until it's too late
5. **Fog of war**: That "blip" at 130 GU could be a single escort or an entire battlegroup
