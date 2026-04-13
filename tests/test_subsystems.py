"""Tests for the Subsystems dataclass."""
from __future__ import annotations

from spacefleet.models.subsystems import Subsystems


def test_default_all_operational():
    s = Subsystems()
    assert s.generator and s.deck and s.engines and s.weapons
    assert s.all_operational()


def test_disable_one():
    s = Subsystems()
    s.engines = False
    assert not s.all_operational()
    assert s.damaged_list() == ["engines"]


def test_repair_all():
    s = Subsystems(generator=False, deck=False)
    s.repair_all()
    assert s.all_operational()
