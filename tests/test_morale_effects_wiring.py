"""Verify combat call sites use morale_effects helpers, not magic constants."""

from __future__ import annotations

import inspect

from spacefleet.combat import boarding, critical_hits, projectile_resolution, resolution


def _src(module: object) -> str:
    return inspect.getsource(module)


def test_resolution_uses_apply_hull_damage_morale() -> None:
    src = _src(resolution)
    assert "apply_hull_damage_morale" in src
    assert "-3 * total_hull_damage" not in src
    assert "-3 * hull_damage" not in src


def test_projectile_resolution_uses_apply_hull_damage_morale() -> None:
    src = _src(projectile_resolution)
    assert "apply_hull_damage_morale" in src
    assert "-3 * total_hull_damage" not in src


def test_boarding_uses_apply_boarding_crew_morale() -> None:
    src = _src(boarding)
    assert "apply_boarding_crew_morale" in src
    assert "-10 * result.total_crew_damage" not in src


def test_critical_hits_uses_apply_critical_hit_morale() -> None:
    src = _src(critical_hits)
    assert "apply_critical_hit_morale" in src
    assert "ship.apply_morale_change(-5)" not in src
