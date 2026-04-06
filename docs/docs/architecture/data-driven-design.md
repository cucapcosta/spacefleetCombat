---
sidebar_position: 3
title: Data-Driven Design
---

# Data-Driven Design

A core architectural principle of Spacefleet Combat is that **game content is defined in data files, not code**. Ship classes, weapon types, critical hit tables, gunnery tables, and scenarios are all YAML files that the engine loads at startup.

## Why Data-Driven?

1. **Moddability**: Anyone can add ships, adjust balance, or create scenarios by editing YAML files
2. **Separation**: Game content (what exists) is separated from game logic (how it behaves)
3. **Validation**: Data files can be validated against schemas independently of game code
4. **Documentation**: The same data files can generate documentation automatically
5. **Iteration**: Balance changes don't require code changes or recompilation

## Data File Formats

### Ship Profiles

Each ship class is a YAML file in `data/ships/<faction>/`:

```yaml
id: lunar_cruiser                    # Unique identifier
name: "Lunar-class Cruiser"         # Display name
classification: cruiser              # escort|light_cruiser|cruiser|battlecruiser|battleship
faction: imperial_navy               # Faction this ship belongs to
points: 180                          # Fleet building cost
leadership: 7                        # Captain competence (2-10)

hull:
  hits: 8                            # Total hit points
  length: 5.0                        # Physical size (km)
  armor_prow: 6                      # Armor value per facing
  armor_port: 5
  armor_starboard: 5
  armor_stern: 4

movement:
  speed: 20                          # Max distance per turn
  turn_rate: 45                      # Max rotation per turn (degrees)
  turn_delay: 10                     # Min straight advance before turning

shields: 2                           # Void shield layers
turrets: 2                           # Point-defense turrets

weapons:                             # List of weapon mounts
  - name: "Port Weapons Battery"
    type: battery                    # References weapon_types.yaml
    arc: port                        # Firing arc
    strength: 6                      # Firepower dice
    range: 45                        # Maximum range (GU)

available_orders:                    # Special orders this ship can receive
  - lock_on
  - all_ahead_full
  - brace_for_impact
```

### Weapon Types

Base weapon behavior is defined in `data/weapons/weapon_types.yaml`:

```yaml
weapon_types:
  battery:
    mechanic: gunnery_table          # How hits are resolved
    ignores_shields: false
    ignores_armor: false
  lance:
    mechanic: flat_roll
    hit_threshold: 4                 # 4+ on D6
    ignores_armor: true
  torpedo:
    mechanic: ordnance
    ignores_shields: true
    interceptable: true
```

### Gunnery Table

The weapon battery hit table in `data/gunnery_table.yaml`:

```yaml
# firepower -> [far_closing, closing, abeam, running, far_running]
gunnery_table:
  1:  [0, 0, 1, 1, 1]
  6:  [1, 2, 2, 3, 4]
  12: [2, 3, 4, 5, 7]
```

### Critical Hits

The critical hit table in `data/critical_hits.yaml`:

```yaml
critical_hit_table:
  7:
    name: "Hull Breach"
    effect: hull_breach
    extra_damage: 1
```

### Scenarios

Battle scenarios in `data/scenarios/`:

```yaml
id: fleet_engagement
battlefield:
  width: 240
  height: 180
deployment:
  player:
    zone: { x_min: 0, x_max: 240, y_min: 0, y_max: 30 }
victory_conditions:
  - type: fleet_destroyed
    threshold: 0.75
```

## Loading Pipeline

```
YAML Files → Loader → Validation → Registry → Game Engine
```

1. **Loader** (`data/loader.py`): Reads YAML files from the data directory
2. **Validation**: Checks required fields, value ranges, reference integrity
3. **Registry**: Stores validated profiles in lookup dictionaries
4. **Game Engine**: Queries registries to instantiate ships and resolve mechanics

## Adding New Content

### Adding a New Ship

1. Create `data/ships/<faction>/<ship_name>.yaml`
2. Fill in the ship profile following the format above
3. The ship is automatically available in fleet building

### Adding a New Faction

1. Create `data/factions/<faction_name>.yaml`
2. Create ship profiles in `data/ships/<faction_name>/`
3. The faction appears in the faction selection menu

### Adjusting Balance

Edit the relevant YAML file:
- Ship too tough? Reduce `hull.hits` or `shields`
- Weapon too strong? Reduce `strength` or `range`
- Gunnery table too generous? Adjust values in `gunnery_table.yaml`
- Critical hits too harsh? Modify effects in `critical_hits.yaml`

No code changes needed for any of these adjustments.
