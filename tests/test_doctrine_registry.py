"""DoctrineRegistry — load the 8 faction doctrines."""

from __future__ import annotations

from spacefleet.core.types import Faction
from spacefleet.data import DoctrineRegistry


def test_loads_all_eight_doctrines() -> None:
    DoctrineRegistry.reset()
    ids = set(DoctrineRegistry.all().keys())
    assert ids == {
        "navy_gunnery_school",
        "commissariat",
        "space_marine_detachment",
        "mechanicus_rites",
        "mark_of_khorne",
        "mark_of_tzeentch",
        "mark_of_nurgle",
        "mark_of_slaanesh",
    }


def test_for_faction_filters() -> None:
    DoctrineRegistry.reset()
    imp = {d.id for d in DoctrineRegistry.for_faction(Faction.IMPERIAL_NAVY)}
    cha = {d.id for d in DoctrineRegistry.for_faction(Faction.CHAOS_FLEET)}
    assert "navy_gunnery_school" in imp and "mark_of_khorne" not in imp
    assert "mark_of_khorne" in cha and "navy_gunnery_school" not in cha


def test_effect_fields() -> None:
    DoctrineRegistry.reset()
    nurgle = DoctrineRegistry.get("mark_of_nurgle")
    assert nurgle.hull_delta == 2 and nurgle.speed_delta == -5.0
    tzeentch = DoctrineRegistry.get("mark_of_tzeentch")
    assert tzeentch.lance_threshold == 3 and tzeentch.hull_delta == -1
    khorne = DoctrineRegistry.get("mark_of_khorne")
    assert khorne.assault_bonus == 3 and khorne.lances_allowed is False
    sm = DoctrineRegistry.get("space_marine_detachment")
    assert sm.assault_bonus == 2 and sm.board_immune is True
    assert DoctrineRegistry.get("commissariat").morale_floor == 20
    assert DoctrineRegistry.get("navy_gunnery_school").column_shift == 1
    assert DoctrineRegistry.get("mechanicus_rites").upgrade_slot_bonus == 1
