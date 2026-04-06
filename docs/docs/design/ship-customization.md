---
sidebar_position: 3
title: Ship Customization
---

# Ship Customization

Ships in Spacefleet Combat are not static stat blocks. You purchase a **hull** and then equip it with **weapons**, **upgrades**, and a **doctrine**. Two ships of the same hull class can play completely differently depending on their loadout.

Inspired by BFG Armada's upgrade system, every ship is a platform you build to fit your fleet's strategy.

## The Three Layers

### 1. Hull (Base Platform)
The hull defines the ship's innate characteristics:
- Hull points, armor values, base speed, turn rate
- **Weapon slots** (how many, what size, what arcs)
- **Upgrade slots** (how many, scales with ship class)
- Base shields and turrets
- Ship classification and points cost

You **cannot change** a hull's innate stats — you can only enhance them through upgrades.

### 2. Weapons (Equipped into Slots)
Each hull has specific **weapon slots** defined by:
- **Size**: Small, Medium, Large (determines what weapons can fit)
- **Arc**: Which direction the slot fires (prow, port, starboard, dorsal)
- **Type constraint**: Some slots only accept certain weapon types (e.g., "torpedo tubes" only accept torpedoes)

You choose which specific weapon to equip in each slot from the weapon catalog. The slot's arc is fixed by the hull — you're choosing the *weapon*, not where it points.

### 3. Upgrades (Passive Enhancements)
Upgrade slots provide passive bonuses to the ship. The number of upgrade slots scales with ship class:

| Classification | Upgrade Slots |
|---------------|--------------|
| Escort | 1 |
| Light Cruiser | 2 |
| Cruiser | 2-3 |
| Battlecruiser | 3 |
| Battleship | 4 |

## Hull Definition

A hull defines the *platform* — what you're building on:

```
LUNAR-CLASS CRUISER HULL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Classification: Cruiser
  Hull Cost: 130 credits (weapons extra)
  Points Value: calculated from hull + loadout

  Hull Hits: 8
  Armor: Prow 6 / Port 5 / Stbd 5 / Stern 4
  Shields: 2 | Turrets: 2
  Speed: 20 | Turn Rate: 45° | Turn Delay: 10
  Leadership: 7

  Weapon Slots:
    [1] Port   — Medium Battery Slot
    [2] Stbd   — Medium Battery Slot
    [3] Prow   — Medium Lance/Battery Slot
    [4] Prow   — Torpedo Tube Slot (torpedo only)

  Upgrade Slots: 3
  Doctrine Slot: 1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Weapon Catalog

### Weapon Batteries (Macro-Cannons)

| Weapon | Size | Strength | Range | Cost | Notes |
|--------|------|----------|-------|------|-------|
| **Macro-Cannon Mk.I** | Small | 2 | 30 | 10 | Basic, cheap |
| **Macro-Cannon Mk.II** | Medium | 4 | 45 | 25 | Standard issue |
| **Macro-Cannon Mk.III** | Medium | 6 | 45 | 40 | Heavy broadside |
| **Macro-Cannon Mk.IV** | Large | 8 | 60 | 60 | Capital-grade |
| **Mars-Pattern Battery** | Large | 10 | 60 | 80 | Rare, devastating |
| **Ryza-Pattern Battery** | Medium | 5 | 60 | 45 | Long-range variant |

### Lances

| Weapon | Size | Strength | Range | Cost | Notes |
|--------|------|----------|-------|------|-------|
| **Lance Mk.I** | Small | 1 | 45 | 15 | Light lance |
| **Lance Mk.II** | Medium | 2 | 60 | 35 | Standard lance |
| **Lance Mk.III** | Large | 4 | 60 | 65 | Heavy lance battery |
| **Disruption Lance** | Medium | 2 | 45 | 45 | +25% critical chance |

### Torpedoes

| Weapon | Size | Strength | Speed | Range | Cost | Notes |
|--------|------|----------|-------|-------|------|-------|
| **Standard Torpedoes** | Torpedo | 4 | 30 | 30 | 20 | Reliable |
| **Guided Torpedoes** | Torpedo | 4 | 25 | 40 | 35 | Longer range, slower |
| **Melta Torpedoes** | Torpedo | 3 | 30 | 30 | 30 | +1 damage per hit, ignores armor |
| **Boarding Torpedoes** | Torpedo | 4 | 25 | 30 | 40 | Deliver assault actions instead of damage |

### Special Weapons

| Weapon | Size | Strength | Range | Cost | Notes |
|--------|------|----------|-------|------|-------|
| **Nova Cannon** | Special (Prow) | 1 | 100 | 100 | Area damage, scatter |

## Upgrade Catalog

### Defensive Upgrades

| Upgrade | Cost | Effect |
|---------|------|--------|
| **Additional Void Shield** | 30 | +1 shield |
| **Auxiliary Shield Capacitor** | 20 | Shields regen +1 per End Phase |
| **Belt Armour** | 25 | First critical hit to any subsystem is ignored |
| **Fire Suppression System** | 15 | Fires have 50% chance to self-extinguish each turn |
| **Extra Turrets** | 15 | +2 turret rating (anti-torpedo defense) |
| **Reinforced Prow** | 20 | Prow armor +1 |

### Offensive Upgrades

| Upgrade | Cost | Effect |
|---------|------|--------|
| **Armour-Piercing Ammo** | 25 | Batteries ignore 1 point of enemy armor at close range |
| **Turbo Weaponry** | 30 | +1 weapon battery strength (all batteries on this ship) |
| **Disruption Overcharge** | 25 | Lance hits cause +25% critical hit chance |
| **Automated Reload** | 20 | Torpedo reload takes 1 fewer turn |

### Mobility Upgrades

| Upgrade | Cost | Effect |
|---------|------|--------|
| **Efficient Plasma Thrusters** | 20 | +5 speed |
| **Enhanced Maneuvers** | 20 | +15° turn rate |
| **Power Ram** | 15 | +50% ramming damage, ram now deals double damage |

### Utility Upgrades

| Upgrade | Cost | Effect |
|---------|------|--------|
| **Improved Augur Array** | 20 | +20 GU sensor range |
| **Crew Quarters** | 15 | +15 max morale |
| **Veteran Crew** | 25 | Crew experience starts at Experienced instead of Green |
| **Navigator's Chamber** | 20 | Micro Warp Jump charges +1 (flagship only) |

## Doctrine Slot

Each ship has one **doctrine slot** — a faction-specific bonus that reflects the ship's operational specialty. Doctrines are chosen during ship configuration and cannot be changed during battle.

### Imperial Navy Doctrines

| Doctrine | Effect |
|----------|--------|
| **Commissariat** | Ship cannot mutiny. Morale cannot drop below 20. |
| **Mechanicus Rites** | +1 upgrade slot on this ship. |
| **Space Marine Detachment** | +2 boarding assault actions. Immune to enemy boarding. |
| **Navy Gunnery School** | All batteries on this ship gain +1 gunnery column shift. |

### Chaos Fleet Doctrines

| Doctrine | Effect |
|----------|--------|
| **Mark of Khorne** | +3 boarding assault actions. Cannot use lances. |
| **Mark of Tzeentch** | Lance hits on 3+ instead of 4+. -1 hull. |
| **Mark of Nurgle** | +2 hull. -5 speed. |
| **Mark of Slaanesh** | +10 speed. -1 shield. |

## Crew Experience

Ships gain crew experience from battles, separate from the commander's XP:

| Level | Name | Battles Required | Bonuses |
|-------|------|-----------------|---------|
| 0 | Green | 0 | No bonuses |
| 1 | Trained | 2 battles survived | +5 morale, -5% ability cooldowns |
| 2 | Experienced | 5 battles survived | +10 morale, -10% cooldowns, +5% crit chance |
| 3 | Veteran | 10 battles survived | +15 morale, -15% cooldowns, +10% crit chance |
| 4 | Elite | 20 battles survived | +20 morale, -20% cooldowns, +15% crit chance, +1 firepower |

Crew experience is **lost if the ship is destroyed**. A replacement ship starts at Green. This makes losing veteran ships painful and encourages preserving your fleet.

## Ship Points Value

A ship's total **points value** for fleet building is calculated from:

```
points = hull_base_cost + sum(weapon_costs) + sum(upgrade_costs) + doctrine_cost
```

This means two Lunar-class Cruisers with different loadouts have different points values. A bare-bones cruiser costs less than a fully kitted one, letting you field more ships at the cost of individual power.

## Example Ship Configuration

```
SHIP CONFIGURATION — "ISS Hammer of Light"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Hull: Lunar-class Cruiser
  Crew: Veteran (Level 3)
  Doctrine: Navy Gunnery School

  WEAPONS:
    [1] Port Medium  — Macro-Cannon Mk.III     (str 6, range 45)
    [2] Stbd Medium  — Macro-Cannon Mk.III     (str 6, range 45)
    [3] Prow Medium  — Lance Mk.II             (str 2, range 60)
    [4] Prow Torpedo — Standard Torpedoes      (str 4, speed 30, range 30)

  UPGRADES:
    [1] Armour-Piercing Ammo    (batteries ignore 1 armor at close range)
    [2] Additional Void Shield  (+1 shield → 3 total)
    [3] Fire Suppression System (50% fire self-extinguish)

  TOTAL POINTS: 130 + 80 + 35 + 20 + 25 + 30 + 15 + 10 = 345
  EFFECTIVE STATS:
    Hull: 8 | Shields: 3 | Turrets: 2
    Speed: 20 | Turn: 45° | Armor: 6/5/5/4
    Morale: 115 (base 100 + 15 veteran)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Fleet Building Interface

```
[Fleet Builder | Admiral Korvus | 1000 pts budget | 655 remaining]>

> buy lunar_cruiser
  Lunar-class Cruiser hull — 130 credits
  Name this ship: ISS Righteous Fury

> equip "ISS Righteous Fury"
  WEAPON SLOTS:
    [1] Port Medium  — EMPTY
    [2] Stbd Medium  — EMPTY
    [3] Prow Medium  — EMPTY
    [4] Prow Torpedo — EMPTY

  > slot 1 macro_cannon_3
    Equipped Macro-Cannon Mk.III in Port Medium slot. (+40 pts)

  > slot 2 macro_cannon_3
    Equipped Macro-Cannon Mk.III in Stbd Medium slot. (+40 pts)

  > slot 3 lance_2
    Equipped Lance Mk.II in Prow Medium slot. (+35 pts)

  > slot 4 standard_torpedoes
    Equipped Standard Torpedoes in Prow Torpedo slot. (+20 pts)

  > upgrade armour_piercing_ammo
    Installed Armour-Piercing Ammo. (+25 pts)

  > done
  ISS Righteous Fury configured. Total: 290 pts.

> fleet status
  ISS Hammer of Light  (Lunar Cruiser)   345 pts  [Veteran]
  ISS Righteous Fury   (Lunar Cruiser)   290 pts  [Green]
  Remaining budget: 365 pts
```
