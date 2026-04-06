---
sidebar_position: 9
title: CLI Commands
---

# CLI Command Reference

All interaction happens through text commands. The prompt is context-sensitive, showing current state.

## Prompt Formats

### Battle Prompt
```
[Turn <N> | <PHASE> | <selected ship> (<FLAGSHIP> if applicable)]>
```

### Campaign Prompt
```
[Campaign | <commander name>]>
```

### Fleet Builder Prompt
```
[Fleet Builder | <commander name> | <budget> pts | <remaining> remaining]>
```

## Battle Commands

### Fleet Information

| Command | Alias | Description |
|---------|-------|-------------|
| `fleet status` | `fs` | Overview of all friendly ships |
| `fleet orders` | `fo` | Current stances and queued orders |
| `fleet summary` | — | Compact one-line-per-ship status |
| `fleet morale` | `fm` | Morale status of all ships |

### Ship Selection

| Command | Description |
|---------|-------------|
| `select <name\|id>` | Select a ship by name or ID |
| `select all` | Select all ships |
| `group <name> <ship1> <ship2>...` | Create a named group |
| `select group <name>` | Select a group |

### Stance Commands (Any Phase)

| Command | Description |
|---------|-------------|
| `stance lock_on` | Switch to Lock On stance |
| `stance brace` | Switch to Brace for Impact |
| `stance reload` | Switch to Reload |
| `stance silent` | Switch to Running Silent |
| `stance standard` | Switch to Standard (default) |
| `stance` | Show current stance and cooldown |

### Commander Abilities (Flagship Only, Any Phase)

| Command | Alias | Description |
|---------|-------|-------------|
| `ability <name>` | `ab` | Use an active ability |
| `ability list` | `al` | Show available abilities and cooldowns |
| `ability micro_warp_jump` | — | Teleport flagship |
| `ability emergency_repairs` | — | Repair flagship hull and extinguish fires |
| `ability call_to_arms` | — | Rally nearby ships, cancel mutiny |
| `ability augur_probe <x> <y>` | — | Deploy sensor probe at coordinates |
| `ability concentrated_fire <target>` | — | Boost accuracy against target |

### Movement Phase Orders

| Command | Alias | Description |
|---------|-------|-------------|
| `move ahead` | `ma` | Full speed, no turn |
| `move turn port <degrees>` | `mt p <deg>` | Turn left during movement |
| `move turn starboard <degrees>` | `mt s <deg>` | Turn right during movement |
| `move to <x> <y>` | — | Auto-plot course toward coordinates |
| `speed <value>` | — | Set desired speed (up to max) |
| `boost` | — | All Ahead Full (burns combustion gauge) |
| `high_energy_turn <port\|stbd> <deg>` | `het` | Sharp turn, costs speed |

### Shooting Phase Orders

| Command | Alias | Description |
|---------|-------|-------------|
| `fire <weapon_slot> at <target>` | — | Fire specific weapon at target |
| `fire all at <target>` | `fa <target>` | Fire all weapons that bear |
| `broadside port at <target>` | `bp <target>` | Fire all port-arc weapons |
| `broadside starboard at <target>` | `bs <target>` | Fire all starboard-arc weapons |
| `target subsystem <sub> on <target>` | `ts` | Focus fire on a specific subsystem |
| `board <target>` | — | Initiate boarding action (close range) |
| `hold fire` | `hf` | Do not fire this turn |

### Ordnance Phase Orders

| Command | Alias | Description |
|---------|-------|-------------|
| `launch torpedoes at <target>` | `lt <target>` | Fire torpedo salvo at target |
| `launch torpedoes bearing <deg>` | — | Fire torpedoes on a heading |

### Information / Scanning (Any Phase)

| Command | Alias | Description |
|---------|-------|-------------|
| `scan` | `sc` | Show all detected contacts |
| `scan <target>` | — | Detailed scan of specific contact |
| `status` | `s` | Selected ship's full status |
| `status weapons` | `sw` | Weapon readiness report |
| `status damage` | `sd` | Damage and critical hit report |
| `status subsystems` | `ss` | Subsystem health |
| `status morale` | `sm` | Morale detail |
| `range <target>` | — | Distance, bearing, closing rate |
| `bearing <target>` | — | Bearing from selected ship |
| `map` | — | ASCII minimap |
| `log` | — | Recent combat log entries |
| `log <N>` | — | Last N log entries |

### Game Flow

| Command | Alias | Description |
|---------|-------|-------------|
| `ready` | `r` | Confirm orders, advance phase |
| `next` | `n` | Alias for ready |
| `undo` | `u` | Undo last order this phase |
| `save <filename>` | — | Save game |
| `load <filename>` | — | Load game |
| `help` | `h` | Available commands for current phase |
| `help <command>` | — | Detailed help for a command |
| `quit` | `q` | Exit game |

## Campaign Commands

### Map and Intel

| Command | Description |
|---------|-------------|
| `map` | Display the sector map |
| `system <name>` | Show system details |
| `intel` | Show known enemy fleet positions |
| `treasury` | Financial overview |
| `objectives` | Campaign objectives and urgency |

### Fleet Management

| Command | Description |
|---------|-------------|
| `fleet status` | Overview of all ships in current fleet |
| `fleet split <name>` | Create a new fleet from selected ships |
| `fleet merge <name>` | Merge a fleet into your current fleet |
| `assign <ship> to <fleet>` | Move a ship between fleets |

### Ship Building (at Shipyard)

| Command | Description |
|---------|-------------|
| `shop hulls` | Browse available ship hulls |
| `shop weapons` | Browse available weapons |
| `shop upgrades` | Browse available upgrades |
| `buy <hull_id>` | Purchase a hull |
| `name <ship> "<name>"` | Name a ship |
| `equip <ship>` | Enter equipment mode for a ship |
| `slot <N> <weapon_id>` | Equip weapon in slot N |
| `upgrade <upgrade_id>` | Install an upgrade |
| `doctrine <doctrine_id>` | Assign a doctrine |
| `unequip <ship> slot <N>` | Remove weapon from slot |
| `scuttle <ship>` | Permanently destroy a ship (recover partial credits) |

### Movement (Campaign Map)

| Command | Description |
|---------|-------------|
| `move to <system>` | Move current fleet to adjacent system |
| `move <fleet> to <system>` | Move a specific fleet |
| `routes from <system>` | Show available warp routes |

### Repairs (at Shipyard)

| Command | Description |
|---------|-------------|
| `repair <ship>` | Repair a damaged ship (costs credits + time) |
| `repair all` | Repair all damaged ships |
| `repair cost <ship>` | Show repair cost estimate |

### Commander

| Command | Description |
|---------|-------------|
| `commander` | Show commander profile |
| `skills` | Show active abilities and passive skills |
| `levelup` | Spend ability/skill points (when available) |
| `flagship <ship>` | Designate a ship as your flagship |

### Turn Flow

| Command | Description |
|---------|-------------|
| `end turn` | End the campaign turn, advance to next |
| `save <filename>` | Save campaign |
| `load <filename>` | Load campaign |
