"""Tests for UpgradeRegistry."""

from __future__ import annotations

from spacefleet.data.upgrade_registry import UpgradeProfile, UpgradeRegistry


def test_loads_default_upgrade():
    UpgradeRegistry.reset()
    up = UpgradeRegistry.get("additional_void_shield")
    assert isinstance(up, UpgradeProfile)
    assert up.cost > 0
    assert up.category == "defensive"
    assert up.effect.get("shields") == 1


def test_all_returns_dict():
    UpgradeRegistry.reset()
    catalog = UpgradeRegistry.all()
    assert "additional_void_shield" in catalog
    assert "fire_suppression_system" in catalog


def test_get_or_none_for_missing():
    UpgradeRegistry.reset()
    assert UpgradeRegistry.get_or_none("nonexistent_xyz") is None
