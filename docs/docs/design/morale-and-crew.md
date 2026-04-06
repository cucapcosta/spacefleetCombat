---
sidebar_position: 8
title: Morale & Crew
---

# Morale and Crew System

Ships have crews. Crews have morale. When morale breaks, ships mutiny. This creates a second axis of attrition beyond hull damage — sometimes you don't destroy a ship, you break its spirit.

## Morale

### Morale Value
Every ship has a **morale value** (0-100 base, can be modified by upgrades and crew experience):
- **100**: Full morale, operating at peak
- **50-99**: Shaken but functional
- **25-49**: Wavering — penalties start applying
- **1-24**: Breaking — severe penalties
- **0**: **MUTINY** — the crew refuses to fight

### Morale Loss Sources

| Event | Morale Loss |
|-------|-------------|
| Hull damage taken | -3 per hull point lost |
| Ship nearby destroyed | -15 (within 30 GU) |
| Flagship destroyed | -30 (all remaining ships) |
| Boarding action received | -5 per assault action |
| Fire (ongoing) | -3 per turn while burning |
| Critical hit received | -5 |
| Enemy ships closing (outnumbered) | -2 per turn if 2:1 outnumbered locally |

### Morale Recovery

| Source | Morale Gain |
|--------|-------------|
| End Phase natural recovery | +5 per turn (if not in combat) |
| Call to Arms ability (flagship) | +30 (ships within 40 GU) |
| Enemy ship destroyed nearby | +5 |
| Battle momentum (winning) | +3 per turn if you've destroyed more than you've lost |
| Docked at friendly system | Full recovery between battles |

### Morale Thresholds

| Morale Range | Effect |
|-------------|--------|
| **75-100** | Full effectiveness. No penalties. |
| **50-74** | **Shaken**: -10% weapon accuracy (batteries shift left on edge cases) |
| **25-49** | **Wavering**: -25% weapon accuracy. Speed -5. Cannot execute special maneuvers. |
| **1-24** | **Breaking**: -50% weapon accuracy. Speed halved. Ship attempts to disengage. |
| **0** | **MUTINY**: Ship stops fighting. See below. |

### Mutiny

When morale hits 0, the ship **mutinies**:
- **Cannot fire weapons**
- **Cannot switch stances** (locked in current stance)
- **Shields stop regenerating**
- **Ship attempts to flee** to the nearest map edge to disengage
- The ship is helpless and vulnerable — easy prey

**Recovering from mutiny**:
- **Call to Arms** ability (flagship) — restores morale, ends mutiny
- **Natural recovery** — if the ship escapes combat range (>80 GU from all enemies), morale slowly recovers
- **Execute crew** — the captain executes mutineers. Ends mutiny immediately, but permanently reduces crew rating by 1 level and max morale by 10.

## Crew

### Crew as a Resource

Ships have a **crew value** representing the number and quality of their personnel:
- Used as the health pool for **boarding actions**
- Affects morale resistance
- Degrades when boarding is received or during Execute Crew orders

### Crew Tiers

Each ship's crew has an **experience tier** that grows over multiple battles:

| Tier | Name | Battles Survived | Morale Bonus | Accuracy Bonus | Cooldown Reduction |
|------|------|-----------------|-------------|----------------|-------------------|
| 0 | Green | 0 | +0 | +0% | 0% |
| 1 | Trained | 2 | +5 | +0% | -5% |
| 2 | Experienced | 5 | +10 | +5% | -10% |
| 3 | Veteran | 10 | +15 | +10% | -15% |
| 4 | Elite | 20 | +20 | +15% | -20% |

Crew experience is **tied to the ship**. If the ship is destroyed, the crew is lost. A replacement ship starts with Green crew.

## Boarding Actions

Boarding is a close-range combat action where you send troops to the enemy ship.

### How Boarding Works

1. **Initiate**: During the Shooting Phase, order a ship within **close range** (5 GU) to board a target
2. **Assault Actions**: The boarding ship delivers a number of **assault actions** based on its tonnage:

| Ship Class | Assault Actions |
|------------|----------------|
| Escort | 1 |
| Light Cruiser | 2 |
| Cruiser | 3 |
| Battlecruiser | 3 |
| Battleship | 4 |

3. **Resolution**: Each assault action does one of the following (roll D6):
   - **1-2**: Repelled. No effect.
   - **3-4**: Crew damage. Target loses crew (morale penalty).
   - **5**: Subsystem hit. One of the target's four subsystems takes a critical.
   - **6**: Devastation. Crew damage AND subsystem critical.

4. **Modifiers**:
   - **Space Marine Detachment** doctrine: +2 assault actions
   - **Lightning Strike** ability: Works at 15 GU range instead of 5
   - **Shields up**: Boarding through shields has -1 to each assault die
   - **Shields down**: No modifier (this is why dropping shields matters for boarding)

### Subsystem Targeting via Boarding

Unlike shooting (which hits random subsystems via the critical table), boarding assault actions let you **choose which subsystem to target** when you score a subsystem hit. This makes boarding a precise, surgical tool:

- Target **Generator** to collapse shields before a lance volley
- Target **Engines** to cripple a fleeing ship
- Target **Weapons** to silence a dangerous broadside
- Target **Deck** to gut morale and push toward mutiny

## The Four Subsystems

Every capital ship (cruiser and above) has four targetable subsystems. Escorts have simplified damage — they die too quickly for subsystem management.

| Subsystem | Effect When Critically Damaged |
|-----------|-------------------------------|
| **Generator** | Shields collapse to 0 and cannot regenerate. Lightning Strike disabled. |
| **Deck** | Cannot switch stances. -20 morale. Boarding defense weakened. |
| **Engines** | Speed halved. Cannot boost (All Ahead Full). Cannot High Energy Turn. |
| **Weapons** | All weapons disabled. Ship cannot fire. |

### Subsystem Repair
- **Emergency Repairs** ability can repair one critical subsystem (flagship only)
- Subsystem crits from **boarding** are "temporary" — they repair automatically after 3 turns
- Subsystem crits from **weapons fire** are "permanent" — last the rest of the battle
- Between battles, all subsystems are fully repaired at a shipyard

## Tactical Implications

### Morale as a Win Condition
You don't always need to destroy every enemy ship. Breaking their morale can cause a cascade:
1. Focus fire on one ship → it's destroyed
2. Nearby ships lose morale from the explosion
3. Board a wavering ship → push it to mutiny
4. More ships see the mutiny → morale drops further
5. The enemy fleet routs without you destroying every hull

### Crew Value
- **Veteran crews are precious** — they make ships significantly more effective
- Losing a ship with an Elite crew (20 battles survived) is devastating
- This creates an incentive to **withdraw damaged ships** rather than fight to the death
- The Execute Crew option during mutiny is a desperate measure — it saves the ship but degrades it permanently

### Boarding Ships
- Ships built for boarding (Space Marine doctrine, high hull, close-range weapons) are a legitimate fleet archetype
- Boarding bypasses shields and armor — it's the counter to heavily armored targets
- But boarding requires **close range** — getting there against a fleet with lances and torpedoes is the challenge
