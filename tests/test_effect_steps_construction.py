"""All twelve effect-step dataclasses construct cleanly."""

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


def test_all_steps_construct() -> None:
    HullRepair(amount_dice="D3")
    ExtinguishFires()
    RepairTempCritical(count=1)
    AreaMoraleRestore(range_gu=40.0, amount=30, cancel_mutiny=True)
    AreaHullDamage(range_gu=15.0, amount_dice="D3", affects_allies=True)
    AreaMoraleDamage(range_gu=15.0, amount=20, affects_allies=True)
    SpawnProbe(radius=30.0, duration=3, detection_level=3)
    ConcentratedFireBuff(range_gu=30.0, column_shift=1, duration=2)
    TimedFleetBuff(buff_id="mark_of_chaos", duration=3, data={"morale_immunity": True})
    BonusTorpedoSalvo(range_gu=50.0)
    Teleport()
    BonusBoardingAssault(actions=3, extended_range_gu=15.0)
