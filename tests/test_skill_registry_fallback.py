"""Registry still works when PyYAML is unavailable / yaml dir missing."""

from __future__ import annotations

from unittest.mock import patch

from spacefleet.data import skill_registry


def test_fallback_populates_universal_abilities() -> None:
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    ids = skill_registry.SkillRegistry.all_active_ids()
    assert "concentrated_fire" in ids
    assert "emergency_repairs" in ids
    assert "call_to_arms" in ids


def test_fallback_populates_universal_passives() -> None:
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    ids = skill_registry.SkillRegistry.all_passive_ids()
    assert "veteran_crews" in ids
    assert "master_gunner" in ids


def test_fallback_levels_and_crew_tiers_present() -> None:
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    lvl2 = skill_registry.SkillRegistry.get_level(2)
    assert lvl2 is not None
    assert lvl2.xp_required > 0

    tier0 = skill_registry.SkillRegistry.get_crew_tier(0)
    assert tier0 is not None
    assert tier0.battles_required == 0


def test_xp_sources_loaded() -> None:
    skill_registry.SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        skill_registry.SkillRegistry.ensure_loaded()

    assert skill_registry.SkillRegistry.xp_source("battle_victory") > 0
