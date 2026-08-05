"""Fleet save/load — JSON round-trip and error handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from spacefleet.core.types import Faction
from spacefleet.models.fleet_spec import FleetSpec, FleetSpecError, ShipSpec
from spacefleet.persistence.fleet_save import default_fleet_dir, load_fleet, save_fleet


def _fleet() -> FleetSpec:
    return FleetSpec(
        name="BF Test",
        faction=Faction.IMPERIAL_NAVY,
        ships=[
            ShipSpec(
                name="Flag",
                hull_id="dauntless_light_cruiser",
                weapons={1: "macro_cannon_3"},
                upgrade_ids=["reinforced_prow"],
                doctrine_id="commissariat",
            )
        ],
    )


def test_save_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "bf_test.json"
    written = save_fleet(_fleet(), path)
    assert written == path
    assert load_fleet(path) == _fleet()


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "f.json"
    save_fleet(_fleet(), path)
    assert path.exists()


def test_load_missing_file_raises() -> None:
    with pytest.raises(FleetSpecError, match="no such fleet file"):
        load_fleet(Path("/nonexistent/fleet.json"))


def test_load_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FleetSpecError, match="not valid JSON"):
        load_fleet(path)


def test_default_fleet_dir_is_a_path() -> None:
    d = default_fleet_dir()
    assert d.name == "fleets"
