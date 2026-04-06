---
sidebar_position: 4
title: Ships & Fleets
---

# Ships and Fleets

## Ship Classifications

Ships are categorized by size and role. Larger ships are tougher and more heavily armed but slower, more expensive, and harder to replace.

| Classification | Hull Hits | Typical Speed | Shields | Weapon Slots | Upgrade Slots | Role |
|---------------|-----------|---------------|---------|-------------|--------------|------|
| **Escort** | 1 | 25-30 | 1 | 1-2 (S) | 1 | Screening, torpedo runs, scouting |
| **Light Cruiser** | 6 | 25 | 1-2 | 3-4 (S-M) | 2 | Patrol, flanking, independent ops |
| **Cruiser** | 8-10 | 20-25 | 2 | 4-5 (M) | 2-3 | Backbone of the fleet, versatile |
| **Battlecruiser** | 10 | 20 | 3 | 5-6 (M-L) | 3 | Heavy fire support, semi-capital |
| **Battleship** | 12+ | 15-20 | 4 | 6-8 (M-L) | 4 | Fleet anchor, maximum firepower |

## Hull Attributes

Every hull defines these innate characteristics (cannot be changed, only enhanced by upgrades):

### Structure
- **Hull Hits**: Total structural integrity. At 0, the ship is destroyed.
- **Length**: Physical size in kilometers. Affects ramming and boarding.
- **Armor** (per facing): Armor value for prow, port, starboard, and stern.

### Movement
- **Speed**: Maximum distance traveled per turn.
- **Turn Rate**: Maximum degrees the ship can rotate per turn.
- **Turn Delay**: Minimum straight-line distance before making a turn.

### Defenses
- **Base Shields**: Starting void shield layers (upgradeable).
- **Base Turrets**: Point-defense turrets that intercept torpedoes (upgradeable).

### Slots
- **Weapon Slots**: Number, size, and arc of weapon mount points. Defined by the hull.
- **Upgrade Slots**: Number of passive upgrade slots. Scales with ship class.
- **Doctrine Slot**: One per ship. Faction-specific bonus.

### Command
- **Leadership**: The base competence of the ship's captain (affects morale checks and some abilities).

See [Ship Customization](ship-customization) for details on equipping weapons and upgrades into slots.

## Subsystems

Every capital ship (cruiser and above) has **four subsystems** that can be targeted and critically damaged:

| Subsystem | Controls | When Critically Damaged |
|-----------|----------|------------------------|
| **Generator** | Shields, energy | Shields collapse, cannot regenerate |
| **Deck** | Stances, morale, crew | Cannot switch stances, -20 morale |
| **Engines** | Movement, maneuvers | Speed halved, cannot boost |
| **Weapons** | All armaments | All weapons disabled |

Escorts are too small for subsystem management — they simply take hull damage and die.

## Crippled Ships

When a ship's hull drops to **50% or below**, it becomes **crippled**:
- Speed is halved
- All weapon strengths are halved (round up)
- Morale drops by 10 immediately
- The ship's status display marks it as `[CRIPPLED]`

## Ship Destruction

At 0 hull hits, a ship is **destroyed**:
- It becomes a drifting hulk (obstacle on the battlefield)
- All crew, upgrades, and experience are **permanently lost**
- Nearby friendly ships lose 15 morale
- If the flagship is destroyed, all ships lose 30 morale and the commander may die (10% chance)

## Fleet Composition

### Points System

Each ship's points value is calculated from its hull, equipped weapons, and upgrades:

```
total_points = hull_cost + sum(weapon_costs) + sum(upgrade_costs) + doctrine_cost
```

### Fleet Capacity

Your fleet's maximum points value is determined by your **commander level**:

| Commander Level | Max Fleet Points |
|----------------|-----------------|
| 1 | 400 |
| 3 | 650 |
| 5 | 1000 |
| 7 | 1500 |
| 9 | 2200 |
| 10 | 2500 |

### Fleet Building Rules

1. **Escorts** operate in squadrons of 2-6 ships of the same class
2. **Flagship**: One ship is designated as the flagship (commander's active abilities work from it)
3. **Hull access**: Higher-tier hulls require higher commander levels (escorts: L1, cruisers: L5, battlecruisers: L7, battleships: L9)
4. **Faction**: All ships in a fleet must be from the same faction

### Escort Squadrons

Escorts operate in squadrons for survivability:
- All ships in a squadron move together (single movement order)
- They fire independently but can be ordered to focus the same target
- The squadron is controlled as one unit
- Individual escorts are removed as they're destroyed

## Factions

### Imperial Navy
**Doctrine**: Close and destroy. Heavy prow armor, devastating torpedo salvos, then broadside at close range.

- **Strengths**: Heavy prow armor, torpedo access, high weapon battery volume, strong boarding
- **Weaknesses**: Slower ships, shorter weapon range on batteries
- **Unique Doctrines**: Commissariat, Mechanicus Rites, Space Marine Detachment, Navy Gunnery School
- **Commander Abilities**: Torpedo Barrage, Boarding Assault

### Chaos Fleet
**Doctrine**: Speed and precision. Maintain range, use superior speed to dictate engagement, lance the enemy apart.

- **Strengths**: Faster ships, longer weapon range, powerful lance arrays
- **Weaknesses**: Lighter armor, no torpedoes (generally), weaker boarding
- **Unique Doctrines**: Mark of Khorne, Mark of Tzeentch, Mark of Nurgle, Mark of Slaanesh
- **Commander Abilities**: Warp Rift, Mark of Chaos

### Future Factions
Additional factions can be added through data files:
- **Ork Pirates**: Cheap, numerous, devastating at close range, terrible at long range
- **Eldar Corsairs**: Extremely fast, fragile, hit-and-run specialists
- **Necrons**: Slow, virtually indestructible, teleportation, self-repair
