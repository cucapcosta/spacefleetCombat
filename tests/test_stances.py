"""Tests for Sprint 2: stances, morale, combustion, and combat modifiers."""

from __future__ import annotations

from spacefleet.combat.resolution import (
    resolve_battery_attack,
    resolve_lance_attack,
)
from spacefleet.core.types import (
    Arc,
    Faction,
    MoraleState,
    ShipClass,
    Stance,
    Vector2D,
    WeaponSize,
    WeaponType,
)
from spacefleet.data.stance_registry import StanceRegistry
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.models.ship_profile import HullProfile, WeaponSlotDef
from spacefleet.models.weapon import WeaponMount, WeaponProfile

# ── Fixtures ──────────────────────────────────────────────────


def _make_hull(
    *,
    faction: Faction = Faction.IMPERIAL_NAVY,
    classification: ShipClass = ShipClass.LIGHT_CRUISER,
) -> HullProfile:
    return HullProfile(
        id="test_hull",
        name="Test Hull",
        classification=classification,
        faction=faction,
        hull_cost=100,
        leadership=8,
        hull_hits=8,
        armor_prow=6,
        armor_port=5,
        armor_starboard=5,
        armor_stern=4,
        speed=20.0,
        turn_rate=45.0,
        shields=2,
        turrets=1,
        sensor_range=40.0,
        weapon_slots=(
            WeaponSlotDef(
                id=1,
                name="Prow",
                arc=Arc.PROW,
                size=WeaponSize.MEDIUM,
                allowed_types=(WeaponType.BATTERY,),
            ),
        ),
        assault_actions=1,
        base_morale=100,
    )


def _make_weapon(
    slot_id: int = 1,
    *,
    weapon_type: WeaponType = WeaponType.BATTERY,
    strength: int = 6,
    wrange: float = 45.0,
    speed: float = 30.0,
) -> WeaponMount:
    wp = WeaponProfile(
        id="test_weapon",
        name="Test Cannon",
        weapon_type=weapon_type,
        size=WeaponSize.MEDIUM,
        strength=strength,
        range=wrange,
        cost=10,
        damage_per_hit=1,
        speed=speed,
        description="",
    )
    return WeaponMount(
        slot_id=slot_id,
        slot_name="Prow",
        weapon=wp,
        arc=Arc.PROW,
    )


def _make_lance(slot_id: int = 1) -> WeaponMount:
    return _make_weapon(
        slot_id,
        weapon_type=WeaponType.LANCE,
        strength=2,
        wrange=60.0,
        speed=0.0,  # instant
    )


def _make_ship(
    name: str = "Attacker",
    *,
    pos: Vector2D | None = None,
    heading: float = 0.0,
    faction: Faction = Faction.IMPERIAL_NAVY,
    weapons: list[WeaponMount] | None = None,
) -> Ship:
    hull = _make_hull(faction=faction)
    return Ship(
        id=name.lower().replace(" ", "_"),
        name=name,
        hull=hull,
        faction=faction,
        position=pos or Vector2D(0.0, 0.0),
        heading=heading,
        speed=0.0,
        hull_current=hull.hull_hits,
        shields_current=hull.shields,
        weapons=weapons if weapons is not None else [_make_weapon()],
        morale=100,
        morale_max=100,
    )


# ── StanceRegistry ────────────────────────────────────────────


class TestStanceRegistry:
    def test_loads_five_stances(self) -> None:
        assert len(StanceRegistry.all()) == 5

    def test_lock_on_gunnery_shift(self) -> None:
        data = StanceRegistry.get("lock_on")
        assert data.gunnery_column_shift == 1

    def test_brace_weapon_modifier(self) -> None:
        data = StanceRegistry.get("brace_for_impact")
        assert data.weapon_strength_modifier == 0.5
        assert data.extra_armor_save == 6

    def test_running_silent_cannot_fire(self) -> None:
        data = StanceRegistry.get("running_silent")
        assert data.cannot_fire is True
        assert data.breaks_on_fire is True

    def test_reload_battery_bonus(self) -> None:
        data = StanceRegistry.get("reload")
        assert data.battery_strength_bonus == 1
        assert data.gunnery_column_shift == -1


# ── Stance Switching ──────────────────────────────────────────


class TestStanceSwitching:
    def test_switch_stance_sets_cooldown(self) -> None:
        ship = _make_ship()
        assert ship.switch_stance(Stance.LOCK_ON) is True
        assert ship.stance == Stance.LOCK_ON
        assert ship.stance_cooldown_remaining == 2

    def test_cannot_switch_during_cooldown(self) -> None:
        ship = _make_ship()
        ship.switch_stance(Stance.LOCK_ON)
        assert ship.switch_stance(Stance.RELOAD) is False
        assert ship.stance == Stance.LOCK_ON

    def test_cooldown_ticks_down(self) -> None:
        ship = _make_ship()
        ship.switch_stance(Stance.LOCK_ON)
        ship.tick_stance_cooldown()
        assert ship.stance_cooldown_remaining == 1
        ship.tick_stance_cooldown()
        assert ship.stance_cooldown_remaining == 0
        assert ship.switch_stance(Stance.RELOAD) is True

    def test_noop_switch_always_allowed(self) -> None:
        ship = _make_ship()
        ship.switch_stance(Stance.LOCK_ON)
        # Switching to same stance is a no-op, always true
        assert ship.switch_stance(Stance.LOCK_ON) is True

    def test_deck_damage_blocks_switch(self) -> None:
        ship = _make_ship()
        ship.subsystem_deck = False
        assert ship.switch_stance(Stance.LOCK_ON) is False

    def test_mutiny_blocks_switch(self) -> None:
        ship = _make_ship()
        ship.morale = 0
        assert ship.switch_stance(Stance.LOCK_ON) is False


# ── Morale ────────────────────────────────────────────────────


class TestMorale:
    def test_morale_state_thresholds(self) -> None:
        ship = _make_ship()
        ship.morale = 100
        assert ship.morale_state() == MoraleState.FULL
        ship.morale = 75
        assert ship.morale_state() == MoraleState.FULL
        ship.morale = 74
        assert ship.morale_state() == MoraleState.SHAKEN
        ship.morale = 50
        assert ship.morale_state() == MoraleState.SHAKEN
        ship.morale = 49
        assert ship.morale_state() == MoraleState.WAVERING
        ship.morale = 25
        assert ship.morale_state() == MoraleState.WAVERING
        ship.morale = 24
        assert ship.morale_state() == MoraleState.BREAKING
        ship.morale = 1
        assert ship.morale_state() == MoraleState.BREAKING
        ship.morale = 0
        assert ship.morale_state() == MoraleState.MUTINY

    def test_apply_morale_clamped(self) -> None:
        ship = _make_ship()
        ship.morale = 5
        ship.apply_morale_change(-100)
        assert ship.morale == 0
        ship.apply_morale_change(999)
        assert ship.morale == ship.morale_max

    def test_morale_loss_from_damage(self) -> None:
        """Battery hits that deal hull damage should reduce target morale."""
        attacker = _make_ship("Attacker", pos=Vector2D(0, 0))
        target = _make_ship(
            "Target",
            pos=Vector2D(0, 20),
            faction=Faction.CHAOS_FLEET,
        )
        target.shields_current = 0  # no shields so hits go through
        dr = DiceRoller(seed=42)
        result = resolve_battery_attack(attacker, attacker.weapons[0], target, dice_roller=dr)
        if result.hull_damage_dealt > 0:
            # Morale should have decreased
            assert target.morale < 100


# ── Combustion ────────────────────────────────────────────────


class TestCombustion:
    def test_regenerate_combustion(self) -> None:
        ship = _make_ship()
        ship.combustion = 50
        gain = ship.regenerate_combustion(15)
        assert gain == 15
        assert ship.combustion == 65

    def test_combustion_clamped_at_max(self) -> None:
        ship = _make_ship()
        ship.combustion = 95
        gain = ship.regenerate_combustion(15)
        assert gain == 5
        assert ship.combustion == 100


# ── Combat Modifiers ──────────────────────────────────────────


class TestCombatModifiers:
    def test_running_silent_blocks_fire(self) -> None:
        attacker = _make_ship("Attacker", pos=Vector2D(0, 0))
        target = _make_ship(
            "Target",
            pos=Vector2D(0, 20),
            faction=Faction.CHAOS_FLEET,
        )
        attacker.switch_stance(Stance.RUNNING_SILENT)
        result = resolve_battery_attack(
            attacker,
            attacker.weapons[0],
            target,
            dice_roller=DiceRoller(seed=1),
        )
        assert result.raw_hits == 0
        assert "cannot fire" in result.message.lower()

    def test_mutiny_blocks_fire(self) -> None:
        attacker = _make_ship("Attacker", pos=Vector2D(0, 0))
        target = _make_ship(
            "Target",
            pos=Vector2D(0, 20),
            faction=Faction.CHAOS_FLEET,
        )
        attacker.morale = 0
        result = resolve_battery_attack(
            attacker,
            attacker.weapons[0],
            target,
            dice_roller=DiceRoller(seed=1),
        )
        assert "mutinied" in result.message.lower()

    def test_weapons_disabled_blocks_fire(self) -> None:
        attacker = _make_ship("Attacker", pos=Vector2D(0, 0))
        target = _make_ship(
            "Target",
            pos=Vector2D(0, 20),
            faction=Faction.CHAOS_FLEET,
        )
        attacker.subsystem_weapons = False
        result = resolve_battery_attack(
            attacker,
            attacker.weapons[0],
            target,
            dice_roller=DiceRoller(seed=1),
        )
        assert "disabled" in result.message.lower()

    def test_lance_running_silent_blocks_fire(self) -> None:
        attacker = _make_ship("Attacker", pos=Vector2D(0, 0), weapons=[_make_lance()])
        target = _make_ship(
            "Target",
            pos=Vector2D(0, 20),
            faction=Faction.CHAOS_FLEET,
        )
        attacker.switch_stance(Stance.RUNNING_SILENT)
        result = resolve_lance_attack(
            attacker,
            attacker.weapons[0],
            target,
            dice_roller=DiceRoller(seed=1),
        )
        assert "cannot fire" in result.message.lower()
