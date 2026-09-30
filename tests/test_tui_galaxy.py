"""Seeded galaxy map model and the braille GalaxyMap widget."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult

from spacefleet.campaign.models import CampaignStatus
from spacefleet.core.types import Faction
from spacefleet.tui.model.galaxy import (
    MARKERS,
    NODE_MARGIN_X,
    NODE_MARGIN_Y,
    SECTOR_NAMES,
    SYSTEM_NAMES,
    Galaxy,
    generate,
    node_states,
)
from spacefleet.tui.widgets.galaxy_map import GalaxyMap

ACTIVE = CampaignStatus.ACTIVE
COMPLETED = CampaignStatus.COMPLETED
DEFEATED = CampaignStatus.DEFEATED


def _plain(galaxy: Galaxy, encounter: int, status: CampaignStatus, w: int = 80, h: int = 20) -> str:
    widget = GalaxyMap()
    widget.set_state(galaxy, encounter, status, Faction.CHAOS_FLEET)
    lines = widget.render_text_lines(w, h)
    assert len(lines) == h
    return "\n".join(line.plain for line in lines)


def test_name_lists_are_large_enough() -> None:
    assert len(set(SYSTEM_NAMES)) >= 25
    assert len(set(SECTOR_NAMES)) >= 10


def test_same_seed_same_galaxy_different_seed_differs() -> None:
    assert generate(7) == generate(7)
    assert generate(7) != generate(8)


def test_generate_does_not_touch_global_random() -> None:
    import random

    random.seed(123)
    expected = random.random()
    random.seed(123)
    generate(99)
    assert random.random() == expected


@pytest.mark.parametrize("seed", range(30))
def test_galaxy_shape_and_bounds(seed: int) -> None:
    galaxy = generate(seed)
    assert galaxy.sector_name in SECTOR_NAMES
    assert len(galaxy.nodes) == 6
    assert len({n.name for n in galaxy.nodes}) == 6
    xs = [n.x for n in galaxy.nodes]
    assert xs == sorted(xs)
    for node in galaxy.nodes:
        assert NODE_MARGIN_X <= node.x <= 1 - NODE_MARGIN_X
        assert NODE_MARGIN_Y <= node.y <= 1 - NODE_MARGIN_Y
    assert 40 <= len(galaxy.stars) <= 80
    for x, y in galaxy.stars:
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_encounter_count_is_configurable() -> None:
    assert len(generate(1, encounters=3).nodes) == 4


def test_node_states_active() -> None:
    assert node_states(1, ACTIVE) == ["current", "next", "unknown", "unknown", "unknown", "final"]
    assert node_states(3, ACTIVE) == [
        "cleared",
        "cleared",
        "current",
        "next",
        "unknown",
        "final",
    ]
    assert node_states(5, ACTIVE) == ["cleared"] * 4 + ["current", "next"]


def test_node_states_completed_and_defeated() -> None:
    assert node_states(5, COMPLETED) == ["cleared"] * 5 + ["current"]
    assert node_states(3, DEFEATED) == [
        "cleared",
        "cleared",
        "current",
        "defeated",
        "unknown",
        "final",
    ]
    assert node_states(5, DEFEATED) == ["cleared"] * 4 + ["current", "defeated"]


def test_markers_cover_every_state() -> None:
    states = {s for e in range(1, 6) for st in CampaignStatus for s in node_states(e, st)}
    assert states <= MARKERS.keys()


@pytest.mark.parametrize("seed", [7, 1, 2024, 31337])
def test_render_encounter_three_markers(seed: int) -> None:
    galaxy = generate(seed)
    text = _plain(galaxy, 3, ACTIVE)
    assert text.count("✓") == 2
    assert text.count("◉") == 1
    assert "YOU" in text
    assert text.count("⚔") == 1
    assert text.count("◎") == 1
    assert "?" in text
    assert f"✦ {galaxy.sector_name}" in text
    assert "COMPLETED" not in text and "DEFEATED" not in text


def test_render_banners() -> None:
    galaxy = generate(7)
    done = _plain(galaxy, 5, COMPLETED)
    assert "COMPLETED" in done
    assert done.count("✓") == 5 and "◉" in done and "⚔" not in done
    lost = _plain(galaxy, 3, DEFEATED)
    assert "DEFEATED" in lost
    assert "✗" in lost and "⚔" not in lost


def test_next_node_is_coloured_by_enemy_faction() -> None:
    galaxy = generate(7)
    for faction, colour in ((Faction.CHAOS_FLEET, "red"), (Faction.IMPERIAL_NAVY, "cyan")):
        widget = GalaxyMap()
        widget.set_state(galaxy, 2, ACTIVE, faction)
        styles = [
            str(span.style)
            for line in widget.render_text_lines(80, 20)
            for span in line.spans
            if line.plain[span.start : span.end] == "⚔"
        ]
        assert styles and colour in styles[0]


@pytest.mark.parametrize("size", [(0, 0), (1, 1), (10, 3), (19, 10), (40, 4), (20, 5)])
def test_tiny_sizes_do_not_crash(size: tuple[int, int]) -> None:
    widget = GalaxyMap()
    widget.set_state(generate(7), 3, ACTIVE, None)
    lines = widget.render_text_lines(*size)
    assert lines
    for line in lines:
        assert len(line.plain) <= max(size[0], 0)


def test_render_without_state_is_blank() -> None:
    lines = GalaxyMap().render_text_lines(30, 6)
    assert len(lines) == 6
    assert all(not line.plain.strip() for line in lines)


def test_galaxy_map_mounts_in_app() -> None:
    galaxy = generate(7)
    seen: list[str] = []

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield GalaxyMap(id="map")

    async def go() -> None:
        app = Host()
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            widget = app.query_one("#map", GalaxyMap)
            widget.set_state(galaxy, 3, ACTIVE, Faction.IMPERIAL_NAVY)
            await pilot.pause()
            seen.append(str(widget.render()))

    asyncio.run(go())
    assert "YOU" in seen[0]
    assert galaxy.sector_name in seen[0]
