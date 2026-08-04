"""UpgradeRegistry — flagship_only flag parsing."""

from __future__ import annotations

from spacefleet.data.upgrade_registry import UpgradeRegistry


def test_navigators_chamber_is_flagship_only() -> None:
    UpgradeRegistry.reset()
    nav = UpgradeRegistry.get("navigators_chamber")
    assert nav.flagship_only is True


def test_other_upgrades_default_not_flagship_only() -> None:
    UpgradeRegistry.reset()
    assert UpgradeRegistry.get("turbo_weaponry").flagship_only is False
    assert UpgradeRegistry.get("additional_void_shield").flagship_only is False
