"""Fleet ships drawn side by side from their hull art, names underneath."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget

from spacefleet.tui.model.ship_art import art_lines, render_art

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import RenderableType
    from textual import events
    from textual.binding import BindingType

    from spacefleet.models.ship_profile import HullProfile

GAP = 3  # columns between ships
ROW_GAP = 1  # blank lines between rows of ships


@dataclass(frozen=True)
class HangarEntry:
    hull: HullProfile
    name: str
    damage_ratio: float = 0.0
    flagship: bool = False


@dataclass(frozen=True)
class _Block:
    """Where one ship sits in the layout (the art plus its name line)."""

    index: int
    x: int
    y: int
    width: int
    height: int


def _label(entry: HangarEntry, selected: bool) -> str:
    pointer = "▸ " if selected else "  "
    star = "★ " if entry.flagship else ""
    return f"{pointer}{star}{entry.name}"


def _block_size(entry: HangarEntry) -> tuple[int, int]:
    lines = art_lines(entry.hull)
    width = max(len(lines[0]), len(_label(entry, True)))
    return width, len(lines)


def layout(entries: Sequence[HangarEntry], width: int) -> list[list[_Block]]:
    """Pack ships left to right into rows no wider than *width* (at least one per row)."""
    rows: list[list[tuple[int, int, int]]] = []  # (index, block width, art height)
    used = 0
    for index, entry in enumerate(entries):
        block_width, art_height = _block_size(entry)
        needed = block_width if not rows or not rows[-1] else used + GAP + block_width
        if rows and rows[-1] and needed <= width:
            rows[-1].append((index, block_width, art_height))
            used = needed
        else:
            rows.append([(index, block_width, art_height)])
            used = block_width
    placed: list[list[_Block]] = []
    y = 0
    for row in rows:
        row_height = max(height for _, _, height in row) + 1
        x = 0
        blocks: list[_Block] = []
        for index, block_width, _ in row:
            blocks.append(_Block(index, x, y, block_width, row_height))
            x += block_width + GAP
        placed.append(blocks)
        y += row_height + ROW_GAP
    return placed


class HangarView(Widget, can_focus=True):
    DEFAULT_CSS = """
    HangarView { height: auto; min-height: 6; padding: 0 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "move(-1)", "Previous ship", show=False),
        Binding("right", "move(1)", "Next ship", show=False),
    ]

    class SelectionChanged(Message):
        """The player moved the selection by key or click."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(
        self,
        entries: Sequence[HangarEntry] = (),
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - Textual's keyword
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._entries: tuple[HangarEntry, ...] = tuple(entries)
        self._selected = 0 if self._entries else -1

    @property
    def entries(self) -> tuple[HangarEntry, ...]:
        return self._entries

    @property
    def selected(self) -> int:
        return self._selected

    def set_entries(self, entries: Sequence[HangarEntry], selected: int = 0) -> None:
        self._entries = tuple(entries)
        self._selected = self._clamp(selected)
        self.refresh(layout=True)

    def select(self, index: int) -> None:
        self._selected = self._clamp(index)
        self.refresh()

    def _clamp(self, index: int) -> int:
        if not self._entries:
            return -1
        return min(max(index, 0), len(self._entries) - 1)

    def _pick(self, index: int) -> None:
        index = self._clamp(index)
        if index == self._selected:
            return
        self._selected = index
        self.refresh()
        self.post_message(self.SelectionChanged(index))

    def action_move(self, step: int) -> None:
        if self._entries:
            self._pick(self._selected + step)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        for row in layout(self._entries, self.content_size.width):
            for block in row:
                inside_x = block.x <= offset.x < block.x + block.width
                inside_y = block.y <= offset.y < block.y + block.height
                if inside_x and inside_y:
                    self.focus()
                    self._pick(block.index)
                    return

    def get_content_height(self, container: object, viewport: object, width: int) -> int:
        rows = layout(self._entries, width)
        if not rows:
            return 1
        last = rows[-1][0]
        return last.y + last.height

    def render(self) -> RenderableType:
        return self.render_text(self.content_size.width)

    def plain_text(self) -> str:
        return self.render_text(self.content_size.width).plain

    def render_text(self, width: int) -> Text:
        if not self._entries:
            return Text("No ships.", style="dim")
        out: list[Text] = []
        for row_index, row in enumerate(layout(self._entries, width)):
            if row_index:
                out.extend(Text() for _ in range(ROW_GAP))
            art_height = row[0].height - 1
            lines = [Text() for _ in range(art_height + 1)]
            for position, block in enumerate(row):
                entry = self._entries[block.index]
                is_selected = block.index == self._selected
                art = render_art(entry.hull, damage_ratio=entry.damage_ratio, selected=is_selected)
                art_width = len(art[0]) if art else 0
                left = (block.width - art_width) // 2
                top = art_height - len(art)
                gap = " " * GAP if position else ""
                for line_no in range(art_height):
                    line = lines[line_no]
                    line.append(gap)
                    line.append(" " * left)
                    if line_no >= top:
                        line.append_text(art[line_no - top])
                    else:
                        line.append(" " * art_width)
                    line.append(" " * (block.width - left - art_width))
                label = _label(entry, is_selected)
                label_left = (block.width - len(label)) // 2
                name_line = lines[art_height]
                name_line.append(gap)
                name_line.append(" " * label_left)
                name_line.append(label, style="bold reverse" if is_selected else "")
                name_line.append(" " * (block.width - label_left - len(label)))
            out.extend(lines)
        for line in out:
            line.rstrip()
        return Text("\n").join(out)
