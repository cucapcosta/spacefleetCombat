"""Authoritative game state for the server.

All mutable battle state lives here.  The ``GameState`` object is the
single source of truth — clients never hold their own copies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spacefleet.core.types import Arc, Faction, Vector2D, heading_to_vector
from spacefleet.data import HullRegistry, WeaponRegistry
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.models.weapon import WeaponMount

if TYPE_CHECKING:
    from spacefleet.models.projectile import Projectile


@dataclass
class GameState:
    """All mutable state for one match."""

    turn: int = 0
    ships: dict[str, Ship] = field(default_factory=dict)
    projectiles: list[Projectile] = field(default_factory=list)
    player_ships: dict[str, list[str]] = field(default_factory=dict)
    ai_ships: list[str] = field(default_factory=list)
    kills: dict[str, int] = field(default_factory=dict)
    fired_this_turn: set[str] = field(default_factory=set)
    dice: DiceRoller = field(default_factory=DiceRoller)
    _next_proj_id: int = 0

    # ── Ship lookups ─────────────────────────────────────────

    def get_ship(self, ship_id: str) -> Ship:
        return self.ships[ship_id]

    def alive_ships(self) -> list[Ship]:
        return [s for s in self.ships.values() if s.alive]

    def alive_ships_for(self, player_id: str) -> list[Ship]:
        ids = self.player_ships.get(player_id, [])
        return [self.ships[sid] for sid in ids if self.ships[sid].alive]

    def all_ships_list(self) -> list[Ship]:
        return list(self.ships.values())

    def enemy_ships_of(self, ship: Ship) -> list[Ship]:
        """All alive ships of a different faction."""
        return [s for s in self.ships.values() if s.alive and s.faction != ship.faction]

    def friendly_ships_of(self, ship: Ship) -> list[Ship]:
        """All alive ships of the same faction (excluding self)."""
        return [
            s
            for s in self.ships.values()
            if s.alive and s.faction == ship.faction and s.id != ship.id
        ]

    def owner_of(self, ship_id: str) -> str | None:
        """Return the player_id that owns *ship_id*, or None for AI ships."""
        for pid, sids in self.player_ships.items():
            if ship_id in sids:
                return pid
        return None

    def owner_lookup(self) -> dict[str, str]:
        """Build a ship_id → player_id mapping for all human-controlled ships."""
        result: dict[str, str] = {}
        for pid, sids in self.player_ships.items():
            for sid in sids:
                result[sid] = pid
        return result

    # ── Projectile IDs ───────────────────────────────────────

    def next_projectile_id(self) -> str:
        self._next_proj_id += 1
        return f"salvo_{self._next_proj_id}"

    # ── Game-over checks ─────────────────────────────────────

    def is_game_over(self) -> bool:
        """True when one faction has no alive ships."""
        factions_alive: set[Faction] = set()
        for s in self.ships.values():
            if s.alive:
                factions_alive.add(s.faction)
        return len(factions_alive) < 2

    # ── Factory methods ──────────────────────────────────────

    @classmethod
    def create_pve(
        cls,
        players: list[str],
        ships_per_player: int = 3,
        *,
        seed: int | None = None,
    ) -> GameState:
        """All players on IMPERIAL_NAVY vs AI CHAOS hulks.

        Each player gets 1 Dauntless + (ships_per_player-1) Sword Frigates.
        AI gets several hulks.
        """
        state = cls(dice=DiceRoller(seed=seed))
        _add_imperial_fleet(state, players, ships_per_player)
        _add_ai_hulks(state, num_hulks=max(2, len(players) * 2))
        return state

    @classmethod
    def create_pvp(
        cls,
        teams: dict[str, Faction],
        ships_per_player: int = 3,
        *,
        seed: int | None = None,
    ) -> GameState:
        """Players assigned to factions.  No AI enemies."""
        state = cls(dice=DiceRoller(seed=seed))
        imperial_players = [p for p, f in teams.items() if f == Faction.IMPERIAL_NAVY]
        chaos_players = [p for p, f in teams.items() if f == Faction.CHAOS_FLEET]

        _add_imperial_fleet(state, imperial_players, ships_per_player, start_x=-50)
        _add_chaos_fleet(state, chaos_players, ships_per_player, start_x=50)
        return state

    @classmethod
    def create_mixed(
        cls,
        imperial: list[str],
        chaos: list[str],
        ships_per_player: int = 3,
        *,
        seed: int | None = None,
    ) -> GameState:
        """PvP with AI hulks on both sides."""
        state = cls(dice=DiceRoller(seed=seed))
        _add_imperial_fleet(state, imperial, ships_per_player, start_x=-50)
        _add_chaos_fleet(state, chaos, ships_per_player, start_x=50)
        _add_ai_hulks(state, num_hulks=2, faction=Faction.CHAOS_FLEET, center_x=60)
        _add_ai_hulks(state, num_hulks=2, faction=Faction.IMPERIAL_NAVY, center_x=-60)
        return state


# ── Fleet-building helpers ───────────────────────────────────


def _make_default_weapons(hull_id: str) -> list[WeaponMount]:
    """Build a default weapon loadout for a hull from the registries."""
    if hull_id == "dauntless_light_cruiser":
        mc2 = WeaponRegistry.get("macro_cannon_2")
        mc3 = WeaponRegistry.get("macro_cannon_3")
        return [
            WeaponMount(slot_id=1, slot_name="Port Battery", arc=Arc.PORT, weapon=mc3),
            WeaponMount(slot_id=2, slot_name="Starboard Battery", arc=Arc.STARBOARD, weapon=mc3),
            WeaponMount(slot_id=3, slot_name="Prow Weapon Bay", arc=Arc.PROW, weapon=mc2),
        ]
    if hull_id == "sword_frigate":
        mc1 = WeaponRegistry.get("macro_cannon_1")
        return [
            WeaponMount(slot_id=1, slot_name="Forward Battery", arc=Arc.PROW, weapon=mc1),
            WeaponMount(slot_id=2, slot_name="Secondary Mount", arc=Arc.PROW, weapon=mc1),
        ]
    # Fallback: empty
    return []


def _add_imperial_fleet(
    state: GameState,
    players: list[str],
    ships_per_player: int,
    start_x: float = 0.0,
) -> None:
    """Give each player 1 Dauntless + frigates, facing north."""
    dauntless_hull = HullRegistry.get("dauntless_light_cruiser")
    sword_hull = HullRegistry.get("sword_frigate")

    for i, player_id in enumerate(players):
        state.player_ships[player_id] = []
        state.kills[player_id] = 0
        base_y = i * 20.0  # spread players apart

        # Flagship — Dauntless
        flag_id = f"{player_id}_dauntless"
        flag_name = f"ISS {player_id.title()}'s Dauntless"
        flag = Ship.from_profile(
            flag_id,
            flag_name,
            dauntless_hull,
            _make_default_weapons("dauntless_light_cruiser"),
            position=Vector2D(start_x, base_y),
            heading=0.0,
        )
        state.ships[flag_id] = flag
        state.player_ships[player_id].append(flag_id)

        # Escorts — Sword Frigates
        for j in range(1, ships_per_player):
            esc_id = f"{player_id}_sword_{j}"
            esc_name = f"ISS {player_id.title()}'s Sword {j}"
            offset_x = -10.0 if j % 2 == 1 else 10.0
            offset_y = -15.0 * j
            esc = Ship.from_profile(
                esc_id,
                esc_name,
                sword_hull,
                _make_default_weapons("sword_frigate"),
                position=Vector2D(start_x + offset_x, base_y + offset_y),
                heading=0.0,
            )
            state.ships[esc_id] = esc
            state.player_ships[player_id].append(esc_id)


def _add_chaos_fleet(
    state: GameState,
    players: list[str],
    ships_per_player: int,
    start_x: float = 50.0,
) -> None:
    """Give each Chaos player ships, facing south."""
    dauntless_hull = HullRegistry.get("dauntless_light_cruiser")
    sword_hull = HullRegistry.get("sword_frigate")

    # Chaos uses same hulls for now (re-skinned as Chaos)
    for i, player_id in enumerate(players):
        state.player_ships[player_id] = []
        state.kills[player_id] = 0
        base_y = i * 20.0

        flag_id = f"{player_id}_raider"
        flag_name = f"Chaos Raider ({player_id.title()})"
        flag = Ship.from_profile(
            flag_id,
            flag_name,
            dauntless_hull,
            _make_default_weapons("dauntless_light_cruiser"),
            position=Vector2D(start_x, base_y),
            heading=180.0,
        )
        # Override faction
        flag.faction = Faction.CHAOS_FLEET
        state.ships[flag_id] = flag
        state.player_ships[player_id].append(flag_id)

        for j in range(1, ships_per_player):
            esc_id = f"{player_id}_escort_{j}"
            esc_name = f"Chaos Escort {j} ({player_id.title()})"
            offset_x = -10.0 if j % 2 == 1 else 10.0
            offset_y = 15.0 * j
            esc = Ship.from_profile(
                esc_id,
                esc_name,
                sword_hull,
                _make_default_weapons("sword_frigate"),
                position=Vector2D(start_x + offset_x, base_y + offset_y),
                heading=180.0,
            )
            esc.faction = Faction.CHAOS_FLEET
            state.ships[esc_id] = esc
            state.player_ships[player_id].append(esc_id)


def _add_ai_hulks(
    state: GameState,
    num_hulks: int = 2,
    faction: Faction = Faction.CHAOS_FLEET,
    center_x: float = 0.0,
    center_y: float = 60.0,
) -> None:
    """Spawn stationary AI-controlled hulks."""
    for _i in range(num_hulks):
        hulk_id = f"ai_hulk_{len(state.ai_ships) + 1}"
        hulk_name = f"Derelict Hulk #{len(state.ai_ships) + 1}"

        angle = state.dice.uniform(0.0, 360.0)
        dist = state.dice.uniform(10.0, 30.0)
        direction = heading_to_vector(angle)
        pos = Vector2D(center_x + direction.x * dist, center_y + direction.y * dist)
        heading = state.dice.uniform(0.0, 360.0)

        hulk = Ship.from_profile(
            hulk_id,
            hulk_name,
            HULK_HULL,
            make_hulk_weapons(),
            position=pos,
            heading=heading,
        )
        state.ships[hulk_id] = hulk
        state.ai_ships.append(hulk_id)
