---
sidebar_position: 1
title: Architecture Overview
---

# Architecture Overview

## Design Principles

### Data-Driven Design
Ship hulls, weapons, upgrades, doctrines, commander skills, scenarios, and game tables are defined in **YAML data files**, not hardcoded. Adding a new ship hull, weapon, or upgrade means creating or editing a YAML file.

### Separation of Concerns
The **game engine** knows nothing about I/O. The **CLI layer** knows nothing about game rules. The **campaign layer** wraps the battle engine without modifying it.

### Immutable State Transitions
Each turn produces a new game state from the previous state plus orders. Enables undo, replay, and deterministic testing.

### Composition over Inheritance
Ships are composed of hull + equipped weapons + upgrades + doctrine. Commanders are composed of level + active abilities + passive skills + traits. No deep class hierarchies.

### Event-Driven Communication
Subsystems communicate through an **event bus**. Ship destruction, critical hits, morale breaks, and commander abilities all emit events that other systems can react to independently.

### Multiplayer-Ready Architecture
The orders-in/state-out design makes the game naturally suited for networked multiplayer. All state transitions are deterministic with seeded dice. Commander builds and fleet states are serializable.

## Layer Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     CLI Layer                             │
│  (app, game_cmd, campaign_cmd, fleet_builder, display)   │
│  User input → Commands → Display results                  │
├──────────────────────────────────────────────────────────┤
│                   Campaign Layer                          │
│  (campaign_state, sector_map, economy, events, shop)     │
│  Strategic map, fleet management, narrative, progression  │
├──────────────────────────────────────────────────────────┤
│                   Commander System                        │
│  (commander, abilities, passive_skills, traits, xp)      │
│  Persistent character, leveling, ability resolution       │
├──────────────────────────────────────────────────────────┤
│                    Game Loop                              │
│  (game_loop, game_state, events, stances)                │
│  Turn orchestration, phase transitions, stance mgmt       │
├──────────────────────────────────────────────────────────┤
│                  Phase Resolvers                          │
│  (command, movement, shooting, ordnance, end)            │
│  Pure game logic per turn phase                           │
├──────────────────────────────────────────────────────────┤
│                 Combat Mechanics                          │
│  (gunnery, lance, torpedo, damage, criticals, boarding)  │
│  Hit resolution, damage application, morale effects       │
├──────────────────────────────────────────────────────────┤
│                  Spatial System                           │
│  (geometry, movement, detection, battlefield)            │
│  Vector math, arcs, sensors, terrain                      │
├──────────────────────────────────────────────────────────┤
│                   Ship Models                             │
│  (ship, fleet, weapon, loadout, subsystems, morale)      │
│  Entity definitions, slot-based equipment, state          │
├──────────────────────────────────────────────────────────┤
│                   Data Layer                              │
│  (loader, registries for hulls/weapons/upgrades/etc.)    │
│  YAML loading, validation, catalogs                       │
├──────────────────────────────────────────────────────────┤
│                   Core Types                              │
│  (types, dice)                                           │
│  Enums, Vector2D, dice roller                            │
└──────────────────────────────────────────────────────────┘
```

Arrows only go **downward**. The CLI is the only layer that does I/O.

## Key Abstractions

### `Commander`
A persistent character with level, XP, active ability slots, passive skill slots, and traits. Exists across battles (campaign) or is configured pre-battle (skirmish/multiplayer).

### `Ship`
A runtime entity composed of: hull profile (from YAML) + equipped weapons + equipped upgrades + doctrine + mutable state (position, heading, damage, morale, crew tier, active stance, subsystem health).

### `Loadout`
The collection of weapons, upgrades, and doctrine equipped on a ship. Validated against the hull's slot definitions. Determines the ship's total points value.

### `GameState`
Immutable snapshot of a battle in progress. Contains all ship states, active ordnance, blast markers, turn counter, phase, and events.

### `CampaignState`
Wraps game state with persistent data: commander, fleet roster, sector map, economy, narrative progress, urgency meter.

### `PhaseResolver`
Pure function: `(GameState, Orders) → (GameState, Events)`. One per phase.

### `DiceRoller`
Injectable RNG. Seeded for tests, truly random in production.

### `EventBus`
Pub-sub for decoupled communication. Events: `ShipDamaged`, `ShipDestroyed`, `MoraleBreak`, `Mutiny`, `CriticalHit`, `AbilityUsed`, `StanceSwitched`, etc.

## Dependencies

| Package | Purpose |
|---------|---------|
| `pyyaml` | YAML data loading |
| `prompt-toolkit` | Enhanced CLI (completion, colors, history) |

Dev: `pytest`, `pytest-cov`, `ruff`, `mypy`
