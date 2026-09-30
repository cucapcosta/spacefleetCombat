"""Generic confirmation and text-input modals."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App

from spacefleet.tui.widgets.confirm import ConfirmScreen, TextInputScreen


def _result_of(modal: Any, *keys: str, seen: list[str] | None = None) -> list[Any]:
    results: list[Any] = []

    class Host(App[None]):
        def on_mount(self) -> None:
            self.push_screen(modal, results.append)

    async def go() -> None:
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            for key in keys:
                await pilot.press(key)
                await pilot.pause()
            if seen is not None:
                seen.append(str(modal.query_one("#error").render()))

    asyncio.run(go())
    return results


def test_confirm_yes_key_and_enter_on_default_button() -> None:
    assert _result_of(ConfirmScreen("Sure?"), "y") == [True]
    assert _result_of(ConfirmScreen("Sure?"), "enter") == [True]


def test_confirm_escape_and_n_mean_no() -> None:
    assert _result_of(ConfirmScreen("Sure?"), "escape") == [False]
    assert _result_of(ConfirmScreen("Sure?"), "n") == [False]


def test_text_input_returns_stripped_value_or_none() -> None:
    assert _result_of(TextInputScreen("Name", " Bob "), "enter") == ["Bob"]
    assert _result_of(TextInputScreen("Name", "x"), "escape") == [None]


def test_text_input_validator_keeps_modal_open_with_error() -> None:
    def must_be_digit(value: str) -> str | None:
        return None if value.isdigit() else "digits only"

    modal = TextInputScreen("Seed", "abc", must_be_digit)
    seen: list[str] = []
    results = _result_of(modal, "enter", seen=seen)
    assert results == []
    assert "digits only" in seen[0]


def test_text_input_typing_replaces_default() -> None:
    results = _result_of(TextInputScreen("Seed", ""), "4", "2", "enter")
    assert results == ["42"]
