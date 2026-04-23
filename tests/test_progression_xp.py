"""Commander XP + level up math."""

from __future__ import annotations

from spacefleet.commander.commander import Commander
from spacefleet.commander.progression import apply_xp
from spacefleet.core.types import Faction
from spacefleet.data.skill_registry import SkillRegistry


def _make_cmdr() -> Commander:
    return Commander(
        id="c1",
        name="Test Commander",
        faction=Faction.IMPERIAL_NAVY,
        level=1,
        xp=0,
    )


def test_apply_xp_below_threshold_stays_at_level() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    events = apply_xp(cmdr, 50)
    assert cmdr.level == 1
    assert cmdr.xp == 50
    assert any(ev.__class__.__name__ == "XpGainedEvent" for ev in events)
    assert not any(ev.__class__.__name__ == "LevelUpEvent" for ev in events)


def test_apply_xp_single_level_up() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    events = apply_xp(cmdr, 200)  # level 2 requires 150
    assert cmdr.level == 2
    assert cmdr.xp == 200
    level_ups = [ev for ev in events if ev.__class__.__name__ == "LevelUpEvent"]
    assert len(level_ups) == 1


def test_apply_xp_multi_level_overflow() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    events = apply_xp(cmdr, 500)  # 1 → 2 (150) → 3 (400)
    assert cmdr.level >= 3
    level_ups = [ev for ev in events if ev.__class__.__name__ == "LevelUpEvent"]
    assert len(level_ups) >= 2


def test_apply_xp_capped_at_level_10() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    cmdr = _make_cmdr()
    apply_xp(cmdr, 999_999)
    assert cmdr.level == 10
