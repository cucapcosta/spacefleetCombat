"""HangarView: ships side by side, selection by key and click."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult

from spacefleet.data.hull_registry import HullRegistry
from spacefleet.tui.widgets.hangar_view import HangarEntry, HangarView, layout

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    from textual.pilot import Pilot


def _entries() -> list[HangarEntry]:
    return [
        HangarEntry(HullRegistry.get("emperor_battleship"), "Vengeful Starstorm", flagship=True),
        HangarEntry(HullRegistry.get("lunar_cruiser"), "The Indomitable", damage_ratio=0.4),
        HangarEntry(HullRegistry.get("sword_frigate"), "Blade of Terra"),
    ]


class Host(App[None]):
    def __init__(self, entries: list[HangarEntry]) -> None:
        super().__init__()
        self.entries = entries
        self.changes: list[int] = []

    def compose(self) -> ComposeResult:
        yield HangarView(id="hangar")

    def on_mount(self) -> None:
        view = self.query_one(HangarView)
        view.set_entries(self.entries)
        view.focus()

    def on_hangar_view_selection_changed(self, message: HangarView.SelectionChanged) -> None:
        self.changes.append(message.index)


def _run(
    script: Callable[[Host, HangarView, Pilot[None]], Coroutine[Any, Any, None]],
    *,
    size: tuple[int, int] = (120, 30),
    entries: list[HangarEntry] | None = None,
) -> Host:
    app = Host(_entries() if entries is None else entries)

    async def go() -> None:
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await script(app, app.query_one(HangarView), pilot)

    asyncio.run(go())
    return app


def test_keys_move_selection_and_post_message() -> None:
    seen: list[int] = []

    async def script(app: Host, view: HangarView, pilot: Pilot[None]) -> None:
        assert view.selected == 0
        await pilot.press("right")
        await pilot.press("right")
        await pilot.press("right")  # clamped at the end, no message
        await pilot.pause()
        seen.append(view.selected)
        await pilot.press("left")
        await pilot.pause()
        seen.append(view.selected)

    app = _run(script)
    assert seen == [2, 1]
    assert app.changes == [1, 2, 1]


def test_programmatic_select_does_not_post() -> None:
    async def script(app: Host, view: HangarView, pilot: Pilot[None]) -> None:
        view.select(2)
        view.select(99)
        await pilot.pause()
        assert view.selected == 2
        view.set_entries([])
        assert view.selected == -1
        assert view.entries == ()

    app = _run(script)
    assert app.changes == []


def test_click_selects_ship() -> None:
    async def script(app: Host, view: HangarView, pilot: Pilot[None]) -> None:
        rows = layout(view.entries, view.content_size.width)
        assert len(rows) == 1  # 120 columns fit all three
        third = rows[0][2]
        offset = view.content_region.offset - view.region.offset
        await pilot.click(
            "#hangar", offset=(offset.x + third.x + 2, offset.y + third.y + third.height - 2)
        )
        await pilot.pause()
        assert view.selected == 2

    app = _run(script)
    assert app.changes == [2]


def test_render_shows_names_marker_and_flagship() -> None:
    async def script(app: Host, view: HangarView, pilot: Pilot[None]) -> None:
        text = view.plain_text()
        assert "▸ ★ Vengeful Starstorm" in text
        assert "The Indomitable" in text
        assert "Blade of Terra" in text
        assert text.count("▸") == 1
        assert "▶" in text
        await pilot.press("right")
        await pilot.pause()
        assert "▸ The Indomitable" in view.plain_text()

    _run(script)


def test_names_sit_under_bottom_aligned_art() -> None:
    async def script(app: Host, view: HangarView, pilot: Pilot[None]) -> None:
        lines = view.plain_text().split("\n")
        assert len(lines) == 6  # battleship art is 5 tall + the name line
        assert "Blade of Terra" in lines[5]
        assert "Vengeful Starstorm" in lines[5]

    _run(script)


def test_narrow_width_wraps_to_more_rows() -> None:
    async def script(app: Host, view: HangarView, pilot: Pilot[None]) -> None:
        rows = layout(view.entries, view.content_size.width)
        assert len(rows) >= 2
        text = view.plain_text()
        for entry in view.entries:
            assert entry.name in text
        await pilot.press("right")
        await pilot.pause()

    app = _run(script, size=(50, 30))
    assert app.changes == [1]


def test_tiny_and_empty_do_not_crash() -> None:
    async def script(app: Host, view: HangarView, pilot: Pilot[None]) -> None:
        assert view.plain_text()
        await pilot.press("right")
        await pilot.pause()

    _run(script, size=(12, 10))
    app = _run(script, entries=[])
    assert app.changes == []
