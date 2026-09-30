"""Full-screen battle log: grouping by turn, filter, scrolling, closing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from textual.app import App
from textual.containers import VerticalScroll
from textual.widgets import Input

from spacefleet.tui.model.turn_report import ShipReport, TurnReport
from spacefleet.tui.widgets.event_log import EventLog
from spacefleet.tui.widgets.log_screen import LogScreen, history_lines

if TYPE_CHECKING:
    from textual.pilot import Pilot

HISTORY = [
    (1, ["Vengeful Starstorm [S1] fires Starboard Broadside at Chaos Cruiser [E1]"]),
    (2, ["Iron Duke [S2] lance misses", "Chaos Cruiser [E1] speed 0 → 8"]),
    (3, [f"Iron Duke [S2] event {i}" for i in range(80)]),
]
REPORT = TurnReport(
    turn=3,
    ships=(ShipReport("s1", "S1", "Vengeful Starstorm", True, damage_dealt=4),),
    destroyed=(),
)


def test_history_lines_group_by_turn_with_headers() -> None:
    lines = history_lines(HISTORY[:2])

    assert lines == [
        "── Turn 1 ──",
        HISTORY[0][1][0],
        "── Turn 2 ──",
        *HISTORY[1][1],
    ]


def test_filter_is_case_insensitive_and_keeps_only_matching_turn_headers() -> None:
    lines = history_lines(HISTORY[:2], "  e1] ")

    assert lines == ["── Turn 1 ──", HISTORY[0][1][0], "── Turn 2 ──", HISTORY[1][1][1]]
    assert history_lines(HISTORY[:2], "duke") == ["── Turn 2 ──", HISTORY[1][1][0]]
    assert history_lines(HISTORY, "nothing like this") == []


class Host(App[None]):
    def compose(self):  # type: ignore[no-untyped-def]
        yield EventLog(id="log")


Scenario = Callable[["Pilot[None]", LogScreen], Awaitable[None]]


def _drive(scenario: Scenario) -> None:
    app = Host()

    async def go() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            screen = LogScreen(HISTORY, REPORT)
            await app.push_screen(screen)
            await pilot.pause()
            await scenario(pilot, screen)

    asyncio.run(go())


def test_screen_shows_report_on_top_then_every_turn() -> None:
    async def scenario(pilot: Pilot[None], screen: LogScreen) -> None:
        lines = screen.visible_lines
        assert lines[0] == "Turn 3 report"
        turns = [lines.index(f"── Turn {n} ──") for n in (1, 2, 3)]
        assert turns == sorted(turns)
        assert "Vengeful Starstorm [S1]" in lines[turns[0] + 1]

    _drive(scenario)


def test_slash_filters_then_escape_clears_filter_then_closes() -> None:
    async def scenario(pilot: Pilot[None], screen: LogScreen) -> None:
        box = screen.query_one("#log-filter", Input)
        assert not box.display
        await pilot.press("slash")
        await pilot.pause()
        assert box.display and box.has_focus
        await pilot.press(*"MISSES")
        await pilot.pause()
        assert screen.visible_lines == ["── Turn 2 ──", "Iron Duke [S2] lance misses"]
        await pilot.press("enter")  # keeps the filter, back to scrolling
        await pilot.pause()
        assert screen.query_one("#log-scroll").has_focus
        assert screen.query_text == "MISSES"
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen is screen
        assert not box.display
        assert screen.visible_lines[0] == "Turn 3 report"
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen is not screen

    _drive(scenario)


def test_escape_while_typing_closes_only_the_filter() -> None:
    async def scenario(pilot: Pilot[None], screen: LogScreen) -> None:
        await pilot.press("slash", "d", "u", "k", "e")
        await pilot.pause()
        assert screen.query_text == "duke"
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen is screen
        assert screen.query_text == ""

    _drive(scenario)


def test_uppercase_l_closes_the_screen() -> None:
    async def scenario(pilot: Pilot[None], screen: LogScreen) -> None:
        await pilot.press("L")
        await pilot.pause()
        assert pilot.app.screen is not screen

    _drive(scenario)


def test_scroll_keys_move_through_the_history() -> None:
    async def scenario(pilot: Pilot[None], screen: LogScreen) -> None:
        scroll = screen.query_one("#log-scroll", VerticalScroll)
        assert scroll.has_focus
        assert scroll.scroll_y == 0
        await pilot.press("end")
        await pilot.pause()
        bottom = scroll.scroll_y
        assert bottom > 0
        await pilot.press("pageup")
        await pilot.pause()
        assert scroll.scroll_y < bottom
        await pilot.press("home")
        await pilot.pause()
        assert scroll.scroll_y == 0
        await pilot.press("down")
        await pilot.pause()
        assert scroll.scroll_y > 0

    _drive(scenario)


def test_event_log_wraps_long_lines_instead_of_cutting_them() -> None:
    long = "Vengeful Starstorm [S1] fires Starboard Broadside at Chaos Cruiser [E1] " * 3

    async def scenario(pilot: Pilot[None], screen: LogScreen) -> None:
        await pilot.press("L")
        await pilot.pause()
        log = pilot.app.query_one("#log", EventLog)
        log.set_lines(["── Turn 1 ──", long])
        await pilot.pause()
        assert log.entries == ["── Turn 1 ──", long]
        assert len(log.lines) > 2  # the long entry spans several rows
        assert max(strip.cell_length for strip in log.lines) <= log.scrollable_content_region.width
        rows = len(log.lines)
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        assert len(log.lines) > rows  # re-wrapped narrower
        assert max(strip.cell_length for strip in log.lines) <= log.scrollable_content_region.width

    _drive(scenario)
