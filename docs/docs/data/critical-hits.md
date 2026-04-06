---
sidebar_position: 4
title: Critical Hits
---

# Critical Hit Table Reference

When a weapon hit penetrates armor and deals hull damage, roll **2D6** on the critical hit table. The result applies additional effects beyond the base hull damage.

## The Table

| 2D6 | Name | Effect | Duration |
|-----|------|--------|----------|
| **2** | Shields Collapsed | All shields drop to 0 | 1 turn |
| **3** | Thrusters Damaged | Ship cannot turn | Permanent |
| **4** | Armament Damaged | One random weapon is disabled | Permanent |
| **5** | Prow Armament Damaged | All prow weapons disabled | Permanent |
| **6** | Engine Room Damaged | Speed halved | Permanent |
| **7** | Hull Breach | +1 extra hull damage | Immediate |
| **8** | Engine Room Damaged | Speed halved | Permanent |
| **9** | Fire! | 1 hull damage per turn | Until extinguished |
| **10** | Bulkhead Collapse | D3 extra hull damage | Immediate |
| **11** | Bridge Destroyed | Leadership -3, may lose orders | Permanent |
| **12** | Magazine Detonation! | D6 extra damage (+D6 if carrying torpedoes) | Immediate |

## Probability Distribution

| 2D6 Result | Probability | Cumulative |
|------------|-------------|------------|
| 2 | 2.8% | 2.8% |
| 3 | 5.6% | 8.3% |
| 4 | 8.3% | 16.7% |
| 5 | 11.1% | 27.8% |
| 6 | 13.9% | 41.7% |
| **7** | **16.7%** | **58.3%** |
| 8 | 13.9% | 72.2% |
| 9 | 11.1% | 83.3% |
| 10 | 8.3% | 91.7% |
| 11 | 5.6% | 97.2% |
| 12 | 2.8% | 100% |

**Hull Breach (7)** is the most common result, occurring 1 in 6 critical hits.

## Effect Details

### Shields Collapsed (2)
- All void shields immediately drop to 0
- Shields **cannot regenerate** for 1 full turn
- After 1 turn, normal regeneration resumes

### Thrusters Damaged (3)
- The ship's maneuvering thrusters are destroyed
- **Cannot make any turns** — the ship can only fly straight ahead
- Speed is not affected
- Permanent until the battle ends

### Armament Damaged (4)
- One weapon mount is selected **at random** and disabled
- The weapon cannot fire for the rest of the battle
- If a ship's only weapon is destroyed, it can only ram or board

### Prow Armament Damaged (5)
- **All prow-arc weapons** are disabled
- This includes prow batteries, lances, torpedoes, and nova cannons
- Devastating for prow-heavy ships like the Lunar Cruiser

### Engine Room Damaged (6, 8)
- Speed is **permanently halved** (round down)
- Appears on two results (6 and 8), making it relatively common
- If the engine is damaged twice, speed is quartered
- A crippled engine-damaged ship may be nearly stationary

### Hull Breach (7)
- The most common critical hit
- Deals **+1 hull damage** immediately (on top of the hit that caused the critical)
- No lasting effect beyond the extra damage

### Fire! (9)
- The ship catches fire across multiple decks
- Takes **1 hull damage** at the start of each End Phase
- Each End Phase, make a **leadership check** to extinguish:
  - Success: fire is put out, no further damage
  - Failure: fire continues, 1 more hull damage next turn
- Multiple fires stack (each deals 1 damage per turn)

### Bulkhead Collapse (10)
- Internal structural failure
- Roll **D3** (1-3): the ship takes that many extra hull points of damage immediately
- Can push a ship from healthy to crippled (or crippled to destroyed) in one hit

### Bridge Destroyed (11)
- The command bridge is hit
- Ship's **Leadership is reduced by 3** (to a minimum of 2)
- Special orders become very unreliable
- The ship may fail morale checks more often

### Magazine Detonation! (12)
- Catastrophic ammunition explosion
- Roll **D6**: the ship takes that many extra hull points of damage
- If the ship carries **torpedoes**, roll an **additional D6** damage
- Can destroy a ship outright from a single critical hit
- The rarest result (2.8%) but potentially the most devastating
