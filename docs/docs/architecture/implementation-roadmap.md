---
sidebar_position: 4
title: Implementation Roadmap
---

# Implementation Roadmap

Built in incremental sprints, each producing a testable, increasingly playable result.

## Sprint 1: Foundation

**Goal**: Core types, spatial math, dice, data loading for the new hull+slot format.

| Module | Description |
|--------|-------------|
| `core/types.py` | Vector2D, enums (Faction, Arc, ShipClass, Phase, Stance, WeaponSize) |
| `spatial/geometry.py` | Vector math, angle normalization, arc intersection |
| `dice.py` | D6, 2D6, D3, dice pool rolls (injectable seed) |
| `models/ship_profile.py` | Hull profile with weapon slots (from YAML) |
| `models/weapon.py` | Weapon, WeaponType definitions |
| `models/loadout.py` | Loadout: weapons + upgrades + doctrine, slot validation |
| `data/loader.py` | YAML loading and validation |
| `data/hull_registry.py` | Hull catalog |
| `data/weapon_registry.py` | Weapon catalog |
| `data/upgrade_registry.py` | Upgrade catalog |

**Tests**: Vector math, arc checking, dice, YAML loading, slot validation.

**Deliverable**: Load hull profiles and weapon catalogs from YAML. Validate loadouts against slot constraints.

---

## Sprint 2: Ships, Movement, and Stances

**Goal**: Ships with loadouts exist on the battlefield, can move, and switch stances.

| Module | Description |
|--------|-------------|
| `models/ship.py` | Ship runtime (hull + loadout + state + position + heading) |
| `models/fleet.py` | Fleet container |
| `models/stance.py` | Stance state, cooldown tracking |
| `models/morale.py` | Morale value, thresholds, mutiny state |
| `models/subsystems.py` | Four subsystem health tracking |
| `spatial/movement.py` | Movement algorithm + combustion gauge |
| `phases/movement_phase.py` | Movement phase resolver |

**Tests**: Ship creation with loadout, movement, turning, combustion, stance switching.

**Deliverable**: Ships move on a 2D plane with combustion management and stance switching.

---

## Sprint 3: Combat

**Goal**: Ships can shoot, take damage, and break.

| Module | Description |
|--------|-------------|
| `combat/gunnery.py` | Battery hit table with stance modifiers |
| `combat/lance.py` | Lance resolution |
| `combat/damage.py` | Shield → armor → hull pipeline |
| `combat/critical_hits.py` | Critical table + subsystem targeting |
| `combat/boarding.py` | Boarding assault resolution |
| `combat/morale_effects.py` | Morale changes from combat events |
| `phases/shooting_phase.py` | Shooting phase resolver |

**Tests**: Gunnery table, lance hits, damage pipeline, criticals, subsystem targeting, boarding, morale drops.

**Deliverable**: Full combat resolution including morale and subsystems.

---

## Sprint 4: Game Loop + Basic CLI

**Goal**: First playable battle via CLI.

| Module | Description |
|--------|-------------|
| `core/game_state.py` | Game state management |
| `core/game_loop.py` | Turn/phase orchestration |
| `core/events.py` | Event bus |
| `cli/display.py` | Status tables, damage reports, sensor readouts |
| `cli/game_cmd.py` | Battle command interpreter |
| `cli/colors.py` | ANSI color helpers |
| `cli/app.py` | Main entry point |
| `__main__.py` | `python -m spacefleet` |

**Tests**: Game loop sequencing, CLI parsing.

**Deliverable**: **First playable!** Two fleets fighting via CLI with stances, morale, and subsystems.

---

## Sprint 5: Commander System

**Goal**: Commander abilities and passive skills integrated into battle.

| Module | Description |
|--------|-------------|
| `commander/commander.py` | Commander entity (level, slots) |
| `commander/abilities.py` | Active ability resolution (Micro Warp, Repairs, Rally, etc.) |
| `commander/passive_skills.py` | Fleet-wide passive effect application |
| `commander/progression.py` | XP gain, level up |
| `data/skill_registry.py` | Commander skill catalog |
| `phases/command_phase.py` | Updated: stance + ability management |

**Tests**: Ability cooldowns, charges, effects. Passive skill application. XP and leveling.

**Deliverable**: Commander abilities usable from flagship. Passive skills affect fleet. XP awarded after battle.

---

## Sprint 6: Fleet Builder + Torpedoes

**Goal**: Build custom ships and complete all weapons.

| Module | Description |
|--------|-------------|
| `cli/fleet_builder_cmd.py` | Hull purchasing, weapon equipping, upgrade installation |
| `data/doctrine_registry.py` | Doctrine catalog |
| `combat/torpedo.py` | Torpedo flight and impact |
| `models/ordnance.py` | Torpedo entities |
| `phases/ordnance_phase.py` | Ordnance phase resolver |
| `phases/end_phase.py` | Regeneration, fires, morale checks |
| `spatial/detection.py` | Sensors, detection levels, augur probes |

**Tests**: Fleet builder validation, torpedo mechanics, ordnance phase, detection.

**Deliverable**: **Full battle experience!** Custom loadouts, all weapon types, all phases.

---

## Sprint 7: AI

**Goal**: Play against an AI opponent.

| Module | Description |
|--------|-------------|
| `ai/threat_eval.py` | Threat assessment, target priority |
| `ai/tactics.py` | Ship-level combat behaviors |
| `ai/strategies.py` | Fleet-level strategy |
| `ai/ai_controller.py` | AI order generation |
| `ai/pathfinding.py` | Movement planning |

**Tests**: Target selection, movement planning, strategy transitions.

**Deliverable**: **Full skirmish!** Build a fleet, fight an AI opponent with customized loadouts.

---

## Sprint 8: Campaign

**Goal**: The strategic campaign layer.

| Module | Description |
|--------|-------------|
| `campaign/campaign_state.py` | Master campaign state |
| `campaign/sector_map.py` | Systems, warp routes, control |
| `campaign/economy.py` | Income, upkeep, treasury |
| `campaign/ship_shop.py` | Purchasing at shipyards |
| `campaign/fleet_manager.py` | Fleet splitting, merging, repairs |
| `campaign/urgency.py` | Urgency meter |
| `cli/campaign_cmd.py` | Campaign command interpreter |
| `persistence/campaign_save.py` | Campaign save/load |

**Tests**: Economy balance, movement on sector map, ship purchasing, urgency.

**Deliverable**: **Full campaign!** Play a multi-battle campaign with commander progression.

---

## Sprint 9: Narrative + Polish

**Goal**: Story missions, narrative events, polish.

| Module | Description |
|--------|-------------|
| `campaign/narrative.py` | Story missions, random events, trait triggers |
| `commander/traits.py` | Trait definitions and triggers |
| `cli/minimap.py` | ASCII minimap |
| `spatial/battlefield.py` | Terrain (nebulae, asteroids) |
| `persistence/save_load.py` | Battle save/load |
| Additional data files | More hulls, weapons, balance, campaign stories |

**Tests**: Narrative event triggering, trait acquisition, save/load.

**Deliverable**: Polished game with narrative, terrain, and varied content.

---

## Future Sprints

| Sprint | Feature |
|--------|---------|
| 10 | Multiplayer networking (turn exchange, commander builds) |
| 11 | Additional factions (Orks, Eldar, Necrons) |
| 12 | Advanced campaign features (multiple campaigns, branching narratives) |
| 13 | Curses/TUI interface with better visual presentation |

## Sprint Completion Criteria

- [ ] All listed modules implemented
- [ ] Unit tests >80% coverage
- [ ] `mypy --strict` passes
- [ ] `ruff check` passes
- [ ] Integration test demonstrating the sprint's deliverable
- [ ] Documentation updated
