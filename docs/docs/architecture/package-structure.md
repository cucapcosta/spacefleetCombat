---
sidebar_position: 2
title: Package Structure
---

# Package Structure

```
spacefleetCombat/
├── pyproject.toml
├── README.md
│
├── docs/                              # Docusaurus documentation site
│
├── data/                              # Game data files (YAML)
│   ├── factions/
│   │   ├── imperial_navy.yaml
│   │   └── chaos_fleet.yaml
│   ├── ships/                         # Hull definitions (slots, not baked weapons)
│   │   ├── imperial/
│   │   └── chaos/
│   ├── weapons/
│   │   ├── weapon_types.yaml          # Base mechanic definitions
│   │   └── weapon_catalog.yaml        # Individual equippable weapons
│   ├── upgrades/
│   │   └── upgrades.yaml              # Ship upgrade catalog
│   ├── doctrines/
│   │   └── doctrines.yaml             # Faction doctrines
│   ├── stances/
│   │   └── stances.yaml               # Ship stance definitions
│   ├── commanders/
│   │   ├── skills.yaml                # Active abilities + passive skills
│   │   ├── traits.yaml                # Campaign-earned traits
│   │   └── level_table.yaml           # XP/level progression
│   ├── scenarios/
│   │   └── fleet_engagement.yaml
│   ├── campaign/                      # Campaign map data
│   │   ├── gothic_war.yaml
│   │   └── events/
│   ├── critical_hits.yaml
│   └── gunnery_table.yaml
│
├── src/
│   └── spacefleet/
│       ├── __init__.py
│       ├── __main__.py
│       │
│       ├── core/                      # Engine infrastructure
│       │   ├── types.py               # Vector2D, enums (Faction, Arc, ShipClass, Phase, etc.)
│       │   ├── game_state.py          # GameState snapshots
│       │   ├── game_loop.py           # Turn/phase orchestration
│       │   └── events.py              # Event bus
│       │
│       ├── models/                    # Game entities
│       │   ├── ship_profile.py        # Hull definition (from YAML)
│       │   ├── ship.py                # Ship runtime (hull + loadout + state)
│       │   ├── loadout.py             # Weapon/upgrade/doctrine equipment
│       │   ├── fleet.py               # Fleet collection
│       │   ├── weapon.py              # Weapon instance + WeaponType
│       │   ├── subsystems.py          # Generator, Deck, Engines, Weapons
│       │   ├── morale.py              # Morale tracking, mutiny
│       │   ├── ordnance.py            # Torpedoes, probes (independent entities)
│       │   └── stance.py              # Stance state, cooldown tracking
│       │
│       ├── commander/                 # Commander system
│       │   ├── commander.py           # Commander entity (level, XP, slots)
│       │   ├── abilities.py           # Active ability definitions + resolution
│       │   ├── passive_skills.py      # Passive skill effect application
│       │   ├── traits.py              # Trait definitions + triggers
│       │   └── progression.py         # XP gain, level up logic
│       │
│       ├── phases/                    # Battle phase resolvers
│       │   ├── command_phase.py       # Stance management + ability usage
│       │   ├── movement_phase.py      # Movement + combustion gauge
│       │   ├── shooting_phase.py      # Weapons fire + subsystem targeting
│       │   ├── ordnance_phase.py      # Torpedo movement + impact
│       │   └── end_phase.py           # Regen, fires, morale checks
│       │
│       ├── combat/                    # Combat mechanics
│       │   ├── gunnery.py             # Weapon battery hit table
│       │   ├── lance.py               # Lance resolution
│       │   ├── torpedo.py             # Torpedo mechanics
│       │   ├── damage.py              # Damage pipeline (shields → armor → hull)
│       │   ├── critical_hits.py       # Critical hit table + subsystem damage
│       │   ├── boarding.py            # Boarding assault resolution
│       │   └── morale_effects.py      # Combat morale triggers
│       │
│       ├── spatial/                   # Physics and spatial
│       │   ├── geometry.py            # Vector math, angles, arc checks
│       │   ├── movement.py            # Movement algorithms, combustion
│       │   ├── detection.py           # Sensors, detection levels, probes
│       │   └── battlefield.py         # Terrain, bounds, blast markers
│       │
│       ├── campaign/                  # Campaign layer
│       │   ├── campaign_state.py      # Master campaign state
│       │   ├── sector_map.py          # Systems, warp routes, control
│       │   ├── economy.py             # Income, upkeep, treasury
│       │   ├── ship_shop.py           # Hull/weapon/upgrade purchasing
│       │   ├── fleet_manager.py       # Fleet splitting, merging, repairs
│       │   ├── narrative.py           # Story missions, random events
│       │   └── urgency.py             # Urgency meter mechanics
│       │
│       ├── ai/                        # AI system
│       │   ├── ai_controller.py       # AI order generation
│       │   ├── threat_eval.py         # Threat assessment
│       │   ├── behavior_trees.py      # Behavior tree nodes
│       │   ├── strategies.py          # Fleet-level strategy
│       │   ├── tactics.py             # Ship-level tactics
│       │   └── pathfinding.py         # Movement planning
│       │
│       ├── data/                      # Data loading
│       │   ├── loader.py              # YAML loading + validation
│       │   ├── hull_registry.py       # Ship hull catalog
│       │   ├── weapon_registry.py     # Weapon catalog
│       │   ├── upgrade_registry.py    # Upgrade catalog
│       │   ├── doctrine_registry.py   # Doctrine catalog
│       │   ├── skill_registry.py      # Commander skill catalog
│       │   └── scenario_loader.py     # Scenario/campaign data
│       │
│       ├── cli/                       # CLI interface
│       │   ├── app.py                 # Main app, menus, startup
│       │   ├── game_cmd.py            # In-battle command interpreter
│       │   ├── campaign_cmd.py        # Campaign map command interpreter
│       │   ├── fleet_builder_cmd.py   # Fleet building interface
│       │   ├── display.py             # Text formatting, tables
│       │   ├── colors.py              # ANSI color helpers
│       │   └── minimap.py             # ASCII minimap
│       │
│       ├── persistence/               # Save/load
│       │   ├── save_load.py           # Battle state serialization
│       │   └── campaign_save.py       # Campaign state serialization
│       │
│       └── dice.py                    # Dice roller (injectable)
│
└── tests/
    ├── conftest.py
    ├── test_geometry.py
    ├── test_movement.py
    ├── test_gunnery.py
    ├── test_lance.py
    ├── test_torpedo.py
    ├── test_damage.py
    ├── test_boarding.py
    ├── test_morale.py
    ├── test_detection.py
    ├── test_ship.py
    ├── test_loadout.py
    ├── test_commander.py
    ├── test_abilities.py
    ├── test_stances.py
    ├── test_subsystems.py
    ├── test_game_loop.py
    ├── test_campaign.py
    ├── test_economy.py
    ├── test_ai.py
    ├── test_cli.py
    └── test_data_loader.py
```

## Module Responsibilities

### `core/` — Engine Infrastructure
Turn orchestration, state management, event bus. Generic enough that any turn-based game could use it.

### `models/` — Game Entities
Ships, fleets, weapons, loadouts, subsystems, morale, stances. Defines what things *are* and their basic behaviors. Ships are now hull + loadout + state.

### `commander/` — Commander System *(New)*
The persistent commander entity. Leveling, XP, active abilities (flagship-only with cooldowns/charges), passive fleet-wide skills, campaign traits. Separate from models because the commander exists outside individual battles.

### `phases/` — Battle Phase Resolvers
Pure functions: state + orders → new state + events. One per phase. Updated to handle stances (instead of special orders), commander abilities, combustion gauge, and morale.

### `combat/` — Combat Mechanics
Hit tables, dice, damage pipeline, critical hits, boarding, morale effects. Now includes subsystem targeting and boarding assault resolution.

### `spatial/` — Physics
Positions, angles, arcs, movement algorithms, combustion gauge management, sensor/detection with probes, terrain.

### `campaign/` — Campaign Layer *(New)*
The strategic game layer. Sector map with systems and warp routes, economy (income/upkeep/treasury), ship purchasing and repairs, narrative events and story missions, urgency meter.

### `data/` — Data Loading
YAML loading into typed Python objects. Registries for hulls, weapons, upgrades, doctrines, commander skills. Validates data on load, including weapon-slot compatibility.

### `ai/` — Enemy Intelligence
Evaluates threats, selects targets, generates orders. Produces the same order types as the player.

### `cli/` — User Interface
Command parsing, display formatting, color output. Now includes `campaign_cmd.py` for the strategic map interface and expanded `fleet_builder_cmd.py` for hull+loadout building.

### `persistence/` — Save/Load
Serialization of both battle state and campaign state. Campaign saves include commander, fleet roster, sector map, economy, and narrative progress.
