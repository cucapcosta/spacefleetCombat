"""Hull art data and its Rich rendering."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from spacefleet.data.hull_registry import HullRegistry
from spacefleet.tui.model.ship_art import (
    ALLOWED_CHARS,
    ART_HEIGHT_RANGE,
    ART_WIDTH_RANGE,
    DAMAGE_STYLE,
    HULL_CHARS,
    art_lines,
    render_art,
)

if TYPE_CHECKING:
    from rich.text import Text

    from spacefleet.models.ship_profile import HullProfile

HULLS = sorted(HullRegistry.all().values(), key=lambda hull: hull.id)


def _fits(hull: HullProfile, lines: tuple[str, ...]) -> None:
    low_w, high_w = ART_WIDTH_RANGE[hull.classification]
    low_h, high_h = ART_HEIGHT_RANGE[hull.classification]
    assert low_h <= len(lines) <= high_h, hull.id
    width = max(len(line) for line in lines)
    assert low_w <= width <= high_w, hull.id
    assert all(len(line) == width for line in lines), hull.id


def test_registry_has_all_ten_hulls() -> None:
    assert len(HULLS) >= 10


@pytest.mark.parametrize("hull", HULLS, ids=lambda hull: hull.id)
def test_every_hull_has_art_within_its_class_size(hull: HullProfile) -> None:
    assert hull.art
    lines = art_lines(hull)
    _fits(hull, lines)
    raw_width = ART_WIDTH_RANGE[hull.classification][1]
    assert all(len(line) <= raw_width for line in hull.art)
    assert set("".join(hull.art)) <= ALLOWED_CHARS
    assert "▶" in "".join(hull.art)  # prow tip on the right


@pytest.mark.parametrize("hull", HULLS, ids=lambda hull: hull.id)
def test_fallback_art_fits_class(hull: HullProfile) -> None:
    bare = dataclasses.replace(hull, art=())
    lines = art_lines(bare)
    _fits(bare, lines)
    assert set("".join(lines)) <= ALLOWED_CHARS


def _spans(texts: list[Text]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for text in texts:
        for span in text.spans:
            result.append((text.plain[span.start : span.end], str(span.style)))
    return result


def _hull_cell_count(hull: HullProfile) -> int:
    return sum(ch in HULL_CHARS for ch in "".join(art_lines(hull)))


def _damaged(texts: list[Text]) -> int:
    return sum(1 for chunk, style in _spans(texts) if DAMAGE_STYLE in style for _ in chunk)


def test_render_is_stable_and_one_text_per_line() -> None:
    hull = HullRegistry.get("lunar_cruiser")
    first = render_art(hull, damage_ratio=0.37)
    second = render_art(hull, damage_ratio=0.37)
    assert [t.plain for t in first] == [t.plain for t in second]
    assert _spans(first) == _spans(second)
    assert len(first) == len(art_lines(hull))


def test_styles_differ_by_character_class() -> None:
    hull = HullRegistry.get("lunar_cruiser")
    styles: dict[str, set[str]] = {}
    for chunk, style in _spans(render_art(hull)):
        for ch in chunk:
            styles.setdefault(ch, set()).add(style)
    assert styles["█"] == styles["▀"] == styles["▄"]
    hull_style = next(iter(styles["█"]))
    assert hull_style not in styles["▓"]
    assert hull_style not in styles["▶"]
    assert styles["▓"] != styles["▶"]
    assert " " not in styles


def test_factions_have_different_hull_colours() -> None:
    imperial = _spans(render_art(HullRegistry.get("lunar_cruiser")))
    chaos = _spans(render_art(HullRegistry.get("murder_cruiser")))
    imperial_hull = {style for chunk, style in imperial if "█" in chunk}
    chaos_hull = {style for chunk, style in chaos if "█" in chunk}
    assert imperial_hull.isdisjoint(chaos_hull)


@pytest.mark.parametrize("hull_id", ["sword_frigate", "emperor_battleship", "murder_cruiser"])
def test_damage_marks_a_proportion_of_hull_cells(hull_id: str) -> None:
    hull = HullRegistry.get(hull_id)
    total = _hull_cell_count(hull)
    assert _damaged(render_art(hull, damage_ratio=0.0)) == 0
    half = render_art(hull, damage_ratio=0.5)
    assert abs(_damaged(half) - total / 2) <= 1
    full = render_art(hull, damage_ratio=1.0)
    assert _damaged(full) == total
    assert not any(ch in HULL_CHARS for ch in "".join(t.plain for t in full))
    assert _damaged(render_art(hull, damage_ratio=7.0)) == total
    assert _damaged(render_art(hull, damage_ratio=-1.0)) == 0


def test_damage_grows_monotonically() -> None:
    hull = HullRegistry.get("mars_battlecruiser")
    counts = [_damaged(render_art(hull, damage_ratio=r / 10)) for r in range(11)]
    assert counts == sorted(counts)


def test_selected_is_bold() -> None:
    hull = HullRegistry.get("sword_frigate")
    plain = _spans(render_art(hull))
    bold = _spans(render_art(hull, selected=True))
    assert not any("bold" in style for _, style in plain)
    assert all("bold" in style for _, style in bold)
