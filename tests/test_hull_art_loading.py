"""``art:`` in a ship YAML becomes ``HullProfile.art``."""

from __future__ import annotations

from typing import Any

import yaml

from spacefleet.data.hull_registry import _parse_hull
from spacefleet.data.loader import get_data_dir


def _raw(**extra: Any) -> dict[str, Any]:
    data_dir = get_data_dir()
    assert data_dir is not None
    raw = yaml.safe_load((data_dir / "ships/imperial/sword_frigate.yaml").read_text())
    raw.pop("art", None)
    raw.update(extra)
    return dict(raw)


def test_hull_without_art_has_empty_tuple() -> None:
    hull = _parse_hull(_raw())
    assert hull is not None
    assert hull.art == ()


def test_hull_art_lines_load_as_tuple_of_strings() -> None:
    hull = _parse_hull(_raw(art=[" ▄█▄", "◀███▶"]))
    assert hull is not None
    assert hull.art == (" ▄█▄", "◀███▶")
