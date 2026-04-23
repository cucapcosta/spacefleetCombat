"""Registry parses yaml effects into EffectStep tuples."""

from __future__ import annotations

from spacefleet.commander.abilities import (
    AreaHullDamage,
    AreaMoraleDamage,
    AreaMoraleRestore,
    BonusBoardingAssault,
    BonusTorpedoSalvo,
    ConcentratedFireBuff,
    ExtinguishFires,
    HullRepair,
    RepairTempCritical,
    SpawnProbe,
    Teleport,
    TimedFleetBuff,
)
from spacefleet.data.skill_registry import SkillRegistry


def _reload() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()


def test_emergency_repairs_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("emergency_repairs")
    assert a is not None
    kinds = [type(s) for s in a.steps]
    assert HullRepair in kinds
    assert ExtinguishFires in kinds
    assert RepairTempCritical in kinds


def test_call_to_arms_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("call_to_arms")
    assert a is not None
    assert any(isinstance(s, AreaMoraleRestore) and s.cancel_mutiny for s in a.steps)


def test_warp_rift_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("warp_rift")
    assert a is not None
    assert any(isinstance(s, AreaHullDamage) and s.affects_allies for s in a.steps)
    assert any(isinstance(s, AreaMoraleDamage) and s.affects_allies for s in a.steps)


def test_mark_of_chaos_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("mark_of_chaos")
    assert a is not None
    buffs = [s for s in a.steps if isinstance(s, TimedFleetBuff)]
    assert len(buffs) == 1
    assert buffs[0].data.get("morale_immunity") is True


def test_concentrated_fire_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("concentrated_fire")
    assert a is not None
    buff = next(s for s in a.steps if isinstance(s, ConcentratedFireBuff))
    assert buff.column_shift == 1
    assert buff.range_gu == 30.0


def test_micro_warp_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("micro_warp_jump")
    assert a is not None
    assert any(isinstance(s, Teleport) for s in a.steps)
    assert a.preparation_turns == 1


def test_torpedo_barrage_stub() -> None:
    _reload()
    a = SkillRegistry.get_active("torpedo_barrage")
    assert a is not None
    assert a.sprint6_dependency is True
    assert any(isinstance(s, BonusTorpedoSalvo) for s in a.steps)


def test_augur_probe_stub() -> None:
    _reload()
    a = SkillRegistry.get_active("augur_probe")
    assert a is not None
    assert a.sprint6_dependency is True
    assert any(isinstance(s, SpawnProbe) for s in a.steps)


def test_boarding_assault_steps() -> None:
    _reload()
    a = SkillRegistry.get_active("boarding_assault")
    assert a is not None
    assert any(isinstance(s, BonusBoardingAssault) for s in a.steps)
