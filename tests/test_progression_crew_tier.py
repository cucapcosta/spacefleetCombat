"""Crew tier derivation + increment."""

from __future__ import annotations

from spacefleet.commander.progression import (
    bump_crew_veterancy,
    crew_tier_for,
)
from spacefleet.core.types import Vector2D
from spacefleet.data.demo_data import HULK_HULL, make_hulk_weapons
from spacefleet.data.skill_registry import SkillRegistry
from spacefleet.models.ship import Ship


def _ship() -> Ship:
    return Ship.from_profile(
        "s1",
        "Test Ship",
        HULK_HULL,
        make_hulk_weapons(),
        position=Vector2D(0.0, 0.0),
        heading=0.0,
    )


def test_crew_tier_for_lookup() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    assert crew_tier_for(0) == 0
    assert crew_tier_for(2) == 1  # Trained: battles_required 2
    assert crew_tier_for(5) == 2  # Experienced
    assert crew_tier_for(100) == 4  # Elite cap


def test_crew_tier_lookup_works_without_yaml() -> None:
    from unittest.mock import patch

    from spacefleet.data import skill_registry

    SkillRegistry._loaded = False
    with patch.object(skill_registry, "YAML_AVAILABLE", False):
        SkillRegistry.ensure_loaded()
        assert crew_tier_for(5) == 2
        assert crew_tier_for(100) == 4
    # Restore normal load for subsequent tests
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()


def test_bump_crew_veterancy_advances_tier() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    ship = _ship()
    ship.battles_survived = 1
    assert ship.crew_tier == 0

    events = bump_crew_veterancy(ship)
    assert ship.battles_survived == 2
    assert ship.crew_tier == 1
    assert any(ev.__class__.__name__ == "CrewTierUpEvent" for ev in events)


def test_bump_without_tier_change_emits_no_event() -> None:
    SkillRegistry._loaded = False
    SkillRegistry.ensure_loaded()
    ship = _ship()
    ship.battles_survived = 0
    events = bump_crew_veterancy(ship)
    assert ship.battles_survived == 1
    assert ship.crew_tier == 0
    assert not any(ev.__class__.__name__ == "CrewTierUpEvent" for ev in events)
