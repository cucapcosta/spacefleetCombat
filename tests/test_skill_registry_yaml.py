"""Registry loads the real YAML data under data/commanders/."""

from __future__ import annotations

from spacefleet.data import skill_registry


def test_yaml_loads_all_known_actives() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    ids = skill_registry.SkillRegistry.all_active_ids()
    for expected in (
        "micro_warp_jump",
        "emergency_repairs",
        "call_to_arms",
        "augur_probe",
        "concentrated_fire",
        "torpedo_barrage",
        "boarding_assault",
        "warp_rift",
        "mark_of_chaos",
    ):
        assert expected in ids, f"missing ability: {expected}"


def test_yaml_marks_sprint6_dependencies() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    torp = skill_registry.SkillRegistry.get_active("torpedo_barrage")
    assert torp is not None
    assert torp.sprint6_dependency is True

    probe = skill_registry.SkillRegistry.get_active("augur_probe")
    assert probe is not None
    assert probe.sprint6_dependency is True

    er = skill_registry.SkillRegistry.get_active("emergency_repairs")
    assert er is not None
    assert er.sprint6_dependency is False


def test_yaml_loads_level_and_crew_tier_tables() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    for lvl in range(1, 11):
        assert skill_registry.SkillRegistry.get_level(lvl) is not None

    for tier in range(0, 5):
        assert skill_registry.SkillRegistry.get_crew_tier(tier) is not None


def test_yaml_loads_traits() -> None:
    skill_registry.SkillRegistry._loaded = False
    skill_registry.SkillRegistry.ensure_loaded()

    assert "veteran_of_cadia" in skill_registry.SkillRegistry.all_trait_ids()
