"""Test helpers for terminal UI key-binding tests."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from prompt_toolkit.data_structures import Size
from prompt_toolkit.output import DummyOutput

from spacefleet.cli.terminal_ui import MenuOption, TerminalUI

if TYPE_CHECKING:
    from collections.abc import Iterable


class FakeTerminalUI(TerminalUI):
    """Queue-driven test double with a record of every UI call."""

    def __init__(
        self,
        *,
        choices: Iterable[str | None] = (),
        texts: Iterable[str | None] = (),
        confirmations: Iterable[bool] = (),
    ) -> None:
        super().__init__(interactive=False)
        self.choices = deque(choices)
        self.texts = deque(texts)
        self.confirmations = deque(confirmations)
        self.choose_calls: list[tuple[str, tuple[MenuOption, ...], str, int]] = []
        self.text_calls: list[tuple[str, str, str]] = []
        self.confirm_calls: list[str] = []
        self.show_calls: list[str] = []

    def choose(
        self,
        title: str,
        options: Iterable[MenuOption],
        context: str = "",
        columns: int = 1,
    ) -> str | None:
        self.choose_calls.append((title, tuple(options), context, columns))
        if not self.choices:
            raise AssertionError(f"No queued choice for {title!r}")
        return self.choices.popleft()

    def text(self, label: str, history_key: str, default: str = "") -> str | None:
        self.text_calls.append((label, history_key, default))
        if not self.texts:
            raise AssertionError(f"No queued text for {label!r}")
        return self.texts.popleft()

    def confirm(self, message: str) -> bool:
        self.confirm_calls.append(message)
        if not self.confirmations:
            raise AssertionError(f"No queued confirmation for {message!r}")
        return self.confirmations.popleft()

    def show(self, text: str) -> None:
        self.show_calls.append(text)


class SizedDummyOutput(DummyOutput):
    """A dummy terminal output with a controllable size."""

    def __init__(self, *, columns: int = 80, rows: int = 24) -> None:
        self.columns = columns
        self.rows = rows

    def get_size(self) -> Size:
        return Size(rows=self.rows, columns=self.columns)


class RecordingDummyOutput(SizedDummyOutput):
    """Dummy output that retains rendered terminal text for assertions."""

    def __init__(self, *, columns: int = 80, rows: int = 24) -> None:
        super().__init__(columns=columns, rows=rows)
        self.writes: list[str] = []

    def write(self, data: str) -> None:
        self.writes.append(data)

    def write_raw(self, data: str) -> None:
        self.writes.append(data)
