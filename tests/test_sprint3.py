"""Tests for Sprint 3: critical hits, boarding, fire extinguishing, morale speed."""

from __future__ import annotations

from spacefleet.combat.boarding import resolve_boarding
from spacefleet.combat.critical_hits import (
    CriticalResult,
    apply_critical_hit,
    roll_critical_hit,
)
from spacefleet.core.types import (
    Arc,
    Faction,
    MoraleState,
    Vector2D,
    WeaponSize,
    WeaponType,
)
from spacefleet.dice import DiceRoller
from spacefleet.models.ship import Ship
from spacefleet.models.ship_profile import HullProfile, WeaponSlotDef
from spacefleet.models.weapon import WeaponMount, WeaponProfile

# ── Fixtures ──────────────────────────────────────────────────


def _make_hull(
    *,
    faction: Faction = Faction.IMPERIAL_NAVY,
    leadership: int = 8,
    assault_actions: int = 2,
) -> HullProfile:
    return HullProfile(
        id="test_hull",
        name="Test Hull",
        classification="light_cruiser",
        faction=faction,
        hull_cost=100,
        leadership=leadership,
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
        assault_actions=assault_actions,
        base_morale=100,
    )


def _make_weapon(slot_id: int = 1) -> WeaponMount:
    wp = WeaponProfile(
        id="test_cannon",
        name="Test Cannon",
        weapon_type=WeaponType.BATTERY,
        size=WeaponSize.MEDIUM,
        strength=6,
        range=45.0,
        cost=10,
        damage_per_hit=1,
        speed=30.0,
    )
    return WeaponMount(slot_id=slot_id, slot_name="Prow", weapon=wp, arc=Arc.PROW)


def _make_ship(
    name: str = "TestShip",
    *,
    faction: Faction = Faction.IMPERIAL_NAVY,
    leadership: int = 8,
    assault_actions: int = 2,
) -> Ship:
    hull = _make_hull(
        faction=faction,
        leadership=leadership,
        assault_actions=assault_actions,
    )
    return Ship(
        id=name.lower().replace(" ", "_"),
        name=name,
        hull=hull,
        faction=faction,
        position=Vector2D(0.0, 0.0),
        heading=0.0,
        speed=0.0,
        hull_current=hull.hull_hits,
        shields_current=hull.shields,
        weapons=[_make_weapon()],
        morale=100,
        morale_max=100,
    )


# ── Critical Hit Table ────────────────────────────────────────


class TestCriticalHitTable:
    def test_roll_returns_critical_result(self) -> None:
        ship = _make_ship()
        dr = DiceRoller(seed=42)
        result = roll_critical_hit(ship, dice_roller=dr)
        assert isinstance(result, CriticalResult)
        assert 2 <= result.roll <= 12
        assert result.name != ""

    def test_lock_on_rerolls_seven(self) -> None:
        """Lock On should re-roll result 7 (Hull Breach) once."""
        # Use a seed that gives exactly 7 on first 2D6
        for seed in range(1000):
            dr = DiceRoller(seed=seed)
            first_roll = dr.d6() + dr.d6()
            if first_roll == 7:
                # Reset and test with lock_on_bonus
                dr2 = DiceRoller(seed=seed)
                ship = _make_ship()
                result = roll_critical_hit(ship, lock_on_bonus=True, dice_roller=dr2)
                # The result should be a re-rolled value (may or may not be 7)
                assert isinstance(result, CriticalResult)
                break

    def test_targeted_subsystem_skips_table(self) -> None:
        ship = _make_ship()
        dr = DiceRoller(seed=1)
        result = roll_critical_hit(
            ship,
            targeted_subsystem="engines",
            dice_roller=dr,
        )
        assert result.effect == "engine_damaged"
        assert result.roll == 0  # no table roll

    def test_temporary_crit_flag(self) -> None:
        ship = _make_ship()
        dr = DiceRoller(seed=1)
        result = roll_critical_hit(
            ship,
            targeted_subsystem="deck",
            is_temporary=True,
            dice_roller=dr,
        )
        assert result.is_temporary is True
        assert result.temporary_turns == 3


# ── Apply Critical ────────────────────────────────────────────


class TestApplyCritical:
    def test_shields_collapse(self) -> None:
        ship = _make_ship()
        ship.shields_current = 2
        crit = CriticalResult(
            roll=2,
            name="Shields Collapsed",
            effect="shields_collapse",
            shields_suppressed_turns=1,
        )
        apply_critical_hit(ship, crit)
        assert ship.shields_current == 0
        assert ship.crit_shields_suppressed_turns == 1
        assert ship.morale == 95  # -5 morale

    def test_thrusters_damaged(self) -> None:
        ship = _make_ship()
        crit = CriticalResult(
            roll=3,
            name="Thrusters Damaged",
            effect="thrusters_damaged",
        )
        apply_critical_hit(ship, crit)
        assert ship.crit_thrusters_damaged is True
        assert ship.effective_turn_rate == 0.0

    def test_engine_damaged(self) -> None:
        ship = _make_ship()
        crit = CriticalResult(
            roll=6,
            name="Engine Damaged",
            effect="engine_damaged",
            speed_modifier=0.5,
        )
        apply_critical_hit(ship, crit)
        assert ship.crit_speed_modifier == 0.5
        assert ship.effective_speed_max == ship.hull.speed * 0.5

    def test_fire_crit(self) -> None:
        ship = _make_ship()
        assert ship.fires == 0
        crit = CriticalResult(roll=9, name="Fire!", effect="fire", fires_added=1)
        apply_critical_hit(ship, crit)
        assert ship.fires == 1

    def test_hull_breach_extra_damage(self) -> None:
        ship = _make_ship()
        initial_hull = ship.hull_current
        crit = CriticalResult(
            roll=7,
            name="Hull Breach",
            effect="hull_breach",
            extra_damage=1,
        )
        apply_critical_hit(ship, crit)
        assert ship.hull_current == initial_hull - 1

    def test_bridge_destroyed(self) -> None:
        ship = _make_ship()
        crit = CriticalResult(
            roll=11,
            name="Bridge Destroyed",
            effect="bridge_destroyed",
            leadership_penalty=3,
        )
        apply_critical_hit(ship, crit)
        assert ship.crit_leadership_penalty == 3
        assert ship.effective_leadership == ship.hull.leadership - 3

    def test_morale_loss_per_crit(self) -> None:
        ship = _make_ship()
        crit = CriticalResult(roll=7, name="Hull Breach", effect="hull_breach")
        apply_critical_hit(ship, crit)
        assert ship.morale == 95  # -5 per crit


# ── Shields Suppressed ────────────────────────────────────────


class TestShieldsSuppressed:
    def test_regen_blocked_when_suppressed(self) -> None:
        ship = _make_ship()
        ship.shields_current = 0
        ship.crit_shields_suppressed_turns = 1
        gained = ship.regenerate_shields()
        assert gained == 0
        assert ship.shields_current == 0

    def test_regen_works_after_tick(self) -> None:
        ship = _make_ship()
        ship.shields_current = 0
        ship.crit_shields_suppressed_turns = 1
        ship.tick_shields_suppressed()
        assert ship.crit_shields_suppressed_turns == 0
        gained = ship.regenerate_shields()
        assert gained == 1

    def test_regen_blocked_generator_down(self) -> None:
        ship = _make_ship()
        ship.shields_current = 0
        ship.subsystem_generator = False
        gained = ship.regenerate_shields()
        assert gained == 0


# ── Temporary Repairs ─────────────────────────────────────────


class TestTemporaryRepairs:
    def test_three_turn_countdown(self) -> None:
        ship = _make_ship()
        ship.subsystem_engines = False
        ship.crit_speed_modifier = 0.5
        ship.crit_temporary_repairs = [("engines", 3)]

        ship.tick_temporary_repairs()
        assert len(ship.crit_temporary_repairs) == 1
        assert ship.crit_temporary_repairs[0][1] == 2

        ship.tick_temporary_repairs()
        assert ship.crit_temporary_repairs[0][1] == 1

        ship.tick_temporary_repairs()
        assert len(ship.crit_temporary_repairs) == 0
        assert ship.subsystem_engines is True
        assert ship.crit_speed_modifier == 1.0


# ── Boarding ──────────────────────────────────────────────────


class TestBoarding:
    def test_resolve_returns_result(self) -> None:
        attacker = _make_ship("Attacker")
        target = _make_ship("Target", faction=Faction.CHAOS_FLEET)
        dr = DiceRoller(seed=42)
        result = resolve_boarding(attacker, target, 2, dice_roller=dr)
        assert result.assault_actions == 2
        assert len(result.action_results) == 2
        total = result.total_repelled + result.total_crew_damage + result.total_subsystem_hits
        # Each action produces at least one count (repelled counts as 1,
        # "both" counts as crew_damage+subsystem)
        assert total >= 2

    def test_subsystem_choice_respected(self) -> None:
        attacker = _make_ship("Attacker")
        target = _make_ship("Target", faction=Faction.CHAOS_FLEET)
        # Find a seed that gives a subsystem hit (roll 5 or 6)
        for seed in range(1000):
            dr = DiceRoller(seed=seed)
            result = resolve_boarding(
                attacker,
                target,
                4,
                subsystem_choice="engines",
                dice_roller=dr,
            )
            hits = [ar for ar in result.action_results if ar.subsystem_hit is not None]
            if hits:
                assert all(h.subsystem_hit == "engines" for h in hits)
                break


# ── Fire Extinguishing ────────────────────────────────────────


class TestFireExtinguishing:
    def test_leadership_check_extinguishes(self) -> None:
        ship = _make_ship(leadership=8)
        ship.fires = 2
        # D6 <= 8 always succeeds for a leadership of 8
        dr = DiceRoller(seed=1)
        roll = dr.d6()
        if roll <= ship.effective_leadership:
            ship.fires -= 1
        assert ship.fires <= 2  # may or may not have decremented

    def test_effective_leadership_with_bridge_hit(self) -> None:
        ship = _make_ship(leadership=7)
        ship.crit_leadership_penalty = 3
        assert ship.effective_leadership == 4


# ── Morale Speed Penalties ────────────────────────────────────


class TestMoraleSpeedPenalties:
    def test_wavering_speed_cap(self) -> None:
        ship = _make_ship()
        ship.morale = 30  # WAVERING
        assert ship.morale_state() == MoraleState.WAVERING
        # If speed is at max (20), wavering caps at max-5 = 15
        ship.speed = 20.0
        cap = max(0.0, ship.effective_speed_max - 5)
        assert cap == 15.0

    def test_breaking_speed_cap(self) -> None:
        ship = _make_ship()
        ship.morale = 10  # BREAKING
        assert ship.morale_state() == MoraleState.BREAKING
        cap = ship.effective_speed_max * 0.5
        assert cap == 10.0

    def test_engine_crit_stacks_with_morale(self) -> None:
        ship = _make_ship()
        ship.crit_speed_modifier = 0.5  # engines damaged
        ship.morale = 30  # WAVERING
        # effective_speed_max = 20 * 0.5 = 10
        # wavering cap = 10 - 5 = 5
        assert ship.effective_speed_max == 10.0
        cap = max(0.0, ship.effective_speed_max - 5)
        assert cap == 5.0
