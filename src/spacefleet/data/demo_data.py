"""Hard-coded data for the tech demo.

In the full game all data comes from YAML files via the data-loader.
For the demo we define everything inline to keep the dependency chain
simple and avoid YAML-parsing complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spacefleet.core.types import (
    Arc,
    Faction,
    ShipClass,
    WeaponSize,
    WeaponType,
    heading_to_vector,
)
from spacefleet.models.ship import Ship
from spacefleet.models.ship_profile import HullProfile, WeaponSlotDef
from spacefleet.models.weapon import WeaponMount, WeaponProfile

if TYPE_CHECKING:
    from spacefleet.dice import DiceRoller

# ─────────────────────────────────────────────────────────────────
# Dauntless-class Light Cruiser (player ship)
# ─────────────────────────────────────────────────────────────────

DAUNTLESS_HULL = HullProfile(
    id="dauntless_light_cruiser",
    name="Dauntless-class Light Cruiser",
    classification=ShipClass.LIGHT_CRUISER,
    faction=Faction.IMPERIAL_NAVY,
    hull_cost=80,
    leadership=6,
    hull_hits=4,
    armor_prow=6,
    armor_port=5,
    armor_starboard=5,
    armor_stern=4,
    speed=25.0,
    turn_rate=60.0,
    shields=1,
    turrets=1,
    sensor_range=40.0,
    weapon_slots=(
        WeaponSlotDef(
            1,
            "Port Battery",
            Arc.PORT,
            WeaponSize.MEDIUM,
            (WeaponType.BATTERY,),
        ),
        WeaponSlotDef(
            2,
            "Starboard Battery",
            Arc.STARBOARD,
            WeaponSize.MEDIUM,
            (WeaponType.BATTERY,),
        ),
        WeaponSlotDef(
            3,
            "Prow Weapon Bay",
            Arc.PROW,
            WeaponSize.MEDIUM,
            (WeaponType.BATTERY, WeaponType.LANCE),
        ),
    ),
)

# ─────────────────────────────────────────────────────────────────
# Weapons
# ─────────────────────────────────────────────────────────────────

MACRO_CANNON_2 = WeaponProfile(
    id="macro_cannon_2",
    name="Macro-Cannon Mk.II",
    weapon_type=WeaponType.BATTERY,
    size=WeaponSize.MEDIUM,
    strength=4,
    range=45.0,
    cost=25,
    speed=60.0,
    description="Standard-issue broadside macro-cannons.",
)

MACRO_CANNON_3 = WeaponProfile(
    id="macro_cannon_3",
    name="Macro-Cannon Mk.III",
    weapon_type=WeaponType.BATTERY,
    size=WeaponSize.MEDIUM,
    strength=6,
    range=45.0,
    cost=40,
    speed=60.0,
    description="Heavy broadside batteries. The backbone of Imperial gunnery.",
)

LANCE_2 = WeaponProfile(
    id="lance_2",
    name="Lance Mk.II",
    weapon_type=WeaponType.LANCE,
    size=WeaponSize.MEDIUM,
    strength=2,
    range=60.0,
    cost=35,
    description="Standard lance battery. Cuts through armor with ease.",
)

SALVAGE_GUN = WeaponProfile(
    id="salvage_gun",
    name="Salvage Gun",
    weapon_type=WeaponType.BATTERY,
    size=WeaponSize.SMALL,
    strength=1,
    range=30.0,
    cost=0,
    speed=60.0,
    description="A barely-functional weapon jury-rigged from salvage.",
)

# ─────────────────────────────────────────────────────────────────
# Weapon kits (player chooses one at start)
# ─────────────────────────────────────────────────────────────────


def make_broadside_kit() -> list[WeaponMount]:
    """Kit A — Broadside Brawler.

    Heavy macro-cannons on the broadsides, lighter cannon on the prow.
    Rewards flanking manoeuvres that present the ship's sides.
    """
    return [
        WeaponMount(
            slot_id=1,
            slot_name="Port Battery",
            arc=Arc.PORT,
            weapon=MACRO_CANNON_3,
        ),
        WeaponMount(
            slot_id=2,
            slot_name="Starboard Battery",
            arc=Arc.STARBOARD,
            weapon=MACRO_CANNON_3,
        ),
        WeaponMount(
            slot_id=3,
            slot_name="Prow Weapon Bay",
            arc=Arc.PROW,
            weapon=MACRO_CANNON_2,
        ),
    ]


def make_lance_kit() -> list[WeaponMount]:
    """Kit B — Prow Lancer.

    Balanced broadsides with a prow-mounted lance that bypasses
    armor entirely.  Rewards nose-on approaches.
    """
    return [
        WeaponMount(
            slot_id=1,
            slot_name="Port Battery",
            arc=Arc.PORT,
            weapon=MACRO_CANNON_2,
        ),
        WeaponMount(
            slot_id=2,
            slot_name="Starboard Battery",
            arc=Arc.STARBOARD,
            weapon=MACRO_CANNON_2,
        ),
        WeaponMount(
            slot_id=3,
            slot_name="Prow Weapon Bay",
            arc=Arc.PROW,
            weapon=LANCE_2,
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# Target hulk (enemy practice target)
# ─────────────────────────────────────────────────────────────────

HULK_HULL = HullProfile(
    id="target_hulk",
    name="Derelict Hulk",
    classification=ShipClass.ESCORT,
    faction=Faction.CHAOS_FLEET,
    hull_cost=0,
    leadership=1,
    hull_hits=3,
    armor_prow=4,
    armor_port=4,
    armor_starboard=4,
    armor_stern=4,
    speed=0.0,
    turn_rate=0.0,
    shields=0,
    turrets=0,
    sensor_range=20.0,
    weapon_slots=(
        WeaponSlotDef(
            1,
            "Salvage Gun",
            Arc.DORSAL,
            WeaponSize.SMALL,
            (WeaponType.BATTERY,),
        ),
    ),
)


def make_hulk_weapons() -> list[WeaponMount]:
    """Hulk's single weak dorsal gun (20% chance to fire each turn)."""
    return [
        WeaponMount(
            slot_id=1,
            slot_name="Salvage Gun",
            arc=Arc.DORSAL,
            weapon=SALVAGE_GUN,
        ),
    ]


def spawn_target(
    player: Ship,
    kill_count: int,
    dice: DiceRoller,
) -> Ship:
    """Create a new target hulk at a random position near *player*.

    Called when the previous target is destroyed.  Distance scales
    slightly with kills so the player must move more over time.
    """
    min_dist = 25.0
    max_dist = 40.0 + kill_count * 2  # gradually further away

    angle_deg = dice.uniform(0.0, 360.0)
    dist = dice.uniform(min_dist, max_dist)
    direction = heading_to_vector(angle_deg)
    offset = direction * dist
    pos = player.position + offset
    heading = dice.uniform(0.0, 360.0)

    hulk_id = f"hulk_{kill_count + 1}"
    hulk_name = f"Derelict Hulk #{kill_count + 1}"

    return Ship.from_profile(
        ship_id=hulk_id,
        name=hulk_name,
        hull=HULK_HULL,
        weapons=make_hulk_weapons(),
        position=pos,
        heading=heading,
    )
