---
sidebar_position: 1
title: Game Overview
---

# Spacefleet Combat — Game Design Document

**Spacefleet Combat** is a campaign-driven tactical CLI game of void warfare inspired by *Battlefleet Gothic: Armada*. You take the role of a **Fleet Commander** — a persistent character who levels up, acquires skills, and builds a fleet across a series of battles. You experience combat from the command bridge through text commands, sensor readouts, and damage reports.

In the future, the game will support **multiplayer**, allowing players to roleplay as rival commanders fighting over sectors of space.

## Core Fantasy

You are **Admiral [Your Name]**, commanding a growing battlefleet. You started with a handful of escorts and a battered cruiser. Now, dozens of battles later, your flagship bears the scars of a hundred engagements, your crew are hardened veterans, and your fleet has grown into a force that can challenge anything the enemy throws at you.

Each battle earns your commander experience. Each victory lets you acquire new ships, equip them with the weapons and upgrades you choose, and push deeper into enemy territory on the campaign map. Your fleet is *yours* — built, customized, and commanded by you.

## Design Pillars

### 1. Commander Identity
You are not a faceless player — you are a **Fleet Commander** with a name, a level, skills, and a reputation. Your commander gains experience from battles, unlocks new abilities, and develops passive fleet-wide bonuses. Your flagship carries your active abilities — it matters where you are on the battlefield.

### 2. Ship Customization
Ships are not static stat blocks. You purchase **hulls** and then equip them: choose weapons for each slot, install upgrades, assign crew doctrines. A Lunar-class Cruiser built for long-range lance duels plays completely differently from one built for close-range broadside brawling.

### 3. Campaign Progression
The game is structured as a campaign across a sector map. You control territory, build ships at shipyards, manage an economy, and respond to threats. Story missions advance the narrative. Battles have consequences — damaged ships need repairs, destroyed ships are gone forever, and lost territory means lost income.

### 4. Information Warfare
You can't see everything. Ships have sensor ranges. Contacts start as vague blips and sharpen into identified threats as range closes. Running Silent conceals your ships. Augur Probes extend your vision. Fog of war is real.

### 5. Tactical Depth
Weapon arcs, armor facings, shield management, stances, and formation matter. A well-executed flanking maneuver that exposes the enemy's weak stern armor is vastly more effective than a head-on charge. Your commander's abilities — used from the flagship at the right moment — can turn the tide.

### 6. Future Multiplayer
The architecture supports multiplayer from the start. Two commanders building fleets, customizing ships, and fighting over territory — each roleplaying their faction. The turn-based, orders-in/state-out design makes networked play natural.

## Core Gameplay Loop

### Battle Loop
```
1. ASSESS the situation (fleet status, sensor contacts, range/bearing)
2. DECIDE on strategy (engage, flank, disengage, focus fire)
3. ORDER your ships (stances, movement, weapons fire, commander abilities)
4. RESOLVE the turn (simultaneous execution, combat results)
5. ADAPT to the new situation (damage assessment, morale, enemy response)
```

### Campaign Loop
```
1. REVIEW your sector map (territory, threats, income, shipyards)
2. BUILD and customize ships at your shipyards
3. MOVE your fleets along warp routes
4. FIGHT battles when fleets meet enemies or story missions trigger
5. RECOVER — repair ships, spend XP, acquire upgrades
6. ADVANCE the campaign (narrative events, new objectives)
```

## What This Game Is

- **An RPG** — your commander has a name, level, skills, and a story
- **A fleet builder** — buy hulls, equip weapons, install upgrades, make each ship your own
- **A tactical game** — turn-based combat with simultaneous resolution and deep mechanics
- **A campaign** — persistent territory, economy, fleet management, and narrative
- **A CLI experience** — no sprites, no map rendering (beyond optional ASCII minimap). Text is your interface.

## What This Game Is NOT

- **Not real-time** — turn-based with simultaneous resolution. You have time to think.
- **Not a visual game** — the "display" is text: status tables, sensor readouts, combat logs.
- **Not disposable** — your fleet persists. Losing a battleship *hurts*. Victories *matter*.

## Target Experience

### Campaign Map
```
==========================================================
  SECTOR MAP — Turn 14
==========================================================

  Your Fleet: Admiral Korvus (Level 5) — 3 ships, 1420 pts
  Treasury: 340 credits | Income: +85/turn | Upkeep: -60/turn

  SYSTEMS:
    [YOU] Cadia Prime     — Hive World      — Income: +40
    [YOU] Forge Agrippa   — Forge World     — Tech Access
    [YOU] Port Maw        — Shipyard (Lv.2) — 3/6 construction pts
    [???] Bhein Morr      — Unknown         — Enemy fleet detected
    [ENM] Gothic Sector   — Hive World      — Occupied by Chaos

  OBJECTIVES:
    > Reclaim Gothic Sector (URGENT — 6 turns remaining)

[Campaign | Admiral Korvus]> build lunar_cruiser at port_maw
  Building Lunar-class Cruiser hull at Port Maw...
  Cost: 180 credits | Construction: 3 pts
  Ship will be ready next turn. Assign a name:

[Campaign | Admiral Korvus]> name "ISS Righteous Fury"
```

### Battle
```
==========================================================
  TURN 3 — SHOOTING PHASE
==========================================================

[Turn 3 | SHOOTING | ISS Hammer of Light (FLAGSHIP)]> fire broadside port at defiler

  Port Macro-Cannons Mk.III (str 8): Target IN arc, range OK.
    LOCK ON stance active: column shift right.
    Gunnery table: str 8, running column → 4 hits!
    Defiler shields absorb 2 hits.
    Armor saves vs 2 remaining: [3, 6] → 1 penetrates!
    1 hull damage → Defiler now at 7/10 hull.
    Critical hit check: 2D6 = 9 → FIRE! Decks ablaze!
    Defiler morale: 72 → 58 (hull damage + fire)

[Turn 3 | SHOOTING | ISS Hammer of Light (FLAGSHIP)]> ability emergency_repairs
  Emergency Repairs activated on ISS Hammer of Light!
  Hull: 6/8 → 7/8 (restored 1 point)
  Fire extinguished!
  Charges remaining: 1/2
```
