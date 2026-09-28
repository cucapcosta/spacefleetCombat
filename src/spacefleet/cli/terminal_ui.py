"""Small, injectable terminal interaction primitives."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.utils import get_cwidth

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.input import Input
    from prompt_toolkit.key_binding.key_processor import KeyPressEvent
    from prompt_toolkit.output import Output


@dataclass(frozen=True, slots=True)
class MenuOption:
    """One menu result and the text used to present it."""

    value: str
    label: str
    details: str = ""
    disabled_reason: str | None = None


class TerminalClosed(EOFError):  # noqa: N818 - public name is part of the UI contract
    """Raised when the terminal input stream is closed or interrupted."""


class TerminalUI:
    """Terminal menus and text prompts with injectable I/O."""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        input: Input | None = None,
        output: Output | None = None,
        interactive: bool | None = None,
    ) -> None:
        self._input_fn = input_fn
        self._output_fn = output_fn
        self._interactive = (
            sys.stdin.isatty() and sys.stdout.isatty() if interactive is None else interactive
        )
        self._input = input or (create_input() if self._interactive else None)
        self._output = output or (create_output() if self._interactive else None)
        self._histories: dict[str, InMemoryHistory] = {}
        self._session_depth = 0
        self._session_suspended = 0
        self._panel_renderer: Callable[[int, int], str] | None = None
        self._messages: list[str] = []

    @contextmanager
    def session(self) -> Iterator[None]:
        """Keep all interactive prompts in one alternate-screen session."""
        active = self._interactive and self._output is not None
        depth = self._session_depth
        first = active and depth == 0
        self._session_depth = depth + 1
        if first:
            self._enter_screen()
        try:
            yield
        finally:
            self._session_depth -= 1
            if first:
                self._leave_screen()

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Temporarily leave the alternate screen for a legacy terminal flow."""
        active = self._session_active
        self._session_suspended += 1
        if active:
            self._leave_screen()
        try:
            yield
        finally:
            self._session_suspended -= 1
            if active:
                self._enter_screen()

    @contextmanager
    def panel(self, renderer: Callable[[int, int], str]) -> Iterator[None]:
        """Pin one scoped panel beside or above interactive prompts."""
        previous = self._panel_renderer
        self._panel_renderer = renderer
        try:
            yield
        finally:
            self._panel_renderer = previous

    @property
    def _session_active(self) -> bool:
        return (
            self._interactive
            and self._output is not None
            and self._session_depth > 0
            and self._session_suspended == 0
        )

    def _enter_screen(self) -> None:
        assert self._output is not None
        self._output.enter_alternate_screen()
        self._output.erase_screen()
        self._output.cursor_goto(0, 0)
        self._output.flush()

    def _leave_screen(self) -> None:
        assert self._output is not None
        self._output.show_cursor()
        self._output.quit_alternate_screen()
        self._output.flush()
        if self._messages:
            self._output_fn("\n".join(self._messages))
            self._messages.clear()

    def _prepare_screen(self) -> None:
        if not self._session_active or self._output is None:
            return
        self._output.erase_screen()
        self._output.cursor_goto(0, 0)
        self._output.flush()

    def choose(
        self,
        title: str,
        options: Iterable[MenuOption],
        context: str = "",
        columns: int = 1,
    ) -> str | None:
        """Choose an option, or return ``None`` when the menu is cancelled."""
        choices = tuple(options)
        if not choices:
            return None
        if columns < 1:
            raise ValueError("columns must be at least 1")
        if self._interactive:
            return self._choose_interactive(title, choices, context, columns)
        return self._choose_numbered(title, choices, context)

    def text(self, label: str, history_key: str, default: str = "") -> str | None:
        """Read editable text, keeping independent history for each key."""
        history = self._histories.setdefault(history_key, InMemoryHistory())
        if not self._interactive:
            try:
                value = self._input_fn(f"{label}{f' [{default}]' if default else ''}: ")
            except (EOFError, KeyboardInterrupt, StopIteration) as exc:
                raise TerminalClosed from exc
            if value == "\x1b":
                return None
            result = value or default
            history.append_string(result)
            return result

        bindings = KeyBindings()
        history_items = list(history.load_history_strings())
        history_index = -1
        draft: Document | None = None

        @bindings.add("escape", eager=True)
        def _cancel(event: KeyPressEvent) -> None:
            event.app.exit(result=None)

        @bindings.add("c-c")
        @bindings.add("c-d")
        def _closed(event: KeyPressEvent) -> None:
            event.app.exit(exception=TerminalClosed())

        @bindings.add("enter")
        def _accept(event: KeyPressEvent) -> None:
            event.app.exit(result=event.current_buffer.text)

        @bindings.add("up")
        def _history_up(event: KeyPressEvent) -> None:
            nonlocal draft, history_index
            if not history_items or history_index + 1 >= len(history_items):
                return
            if history_index == -1:
                draft = event.current_buffer.document
            history_index += 1
            value = history_items[history_index]
            event.current_buffer.document = Document(value, cursor_position=len(value))

        @bindings.add("down")
        def _history_down(event: KeyPressEvent) -> None:
            nonlocal history_index
            if history_index == -1:
                return
            history_index -= 1
            if history_index == -1:
                event.current_buffer.document = draft or Document()
                return
            value = history_items[history_index]
            event.current_buffer.document = Document(value, cursor_position=len(value))

        buffer = Buffer(
            document=Document(default, cursor_position=len(default)),
            multiline=False,
        )
        control = BufferControl(buffer=buffer, focusable=True)
        body = HSplit(
            [
                Window(content=FormattedTextControl(f"{label}: "), height=1),
                Window(content=control, height=1),
                *([self._message_window()] if self._messages else []),
            ]
        )
        application: Application[str | None] = Application(
            layout=Layout(self._with_panel(body), focused_element=control),
            key_bindings=bindings,
            full_screen=False,
            erase_when_done=self._session_active,
            input=self._input,
            output=self._output,
        )
        try:
            self._prepare_screen()
            prompt_result = application.run()
        except (EOFError, KeyboardInterrupt) as exc:
            raise TerminalClosed from exc
        if prompt_result is not None:
            history.append_string(prompt_result)
        self._messages.clear()
        return prompt_result

    def confirm(self, message: str) -> bool:
        """Ask for confirmation with the safe cancellation choice selected."""
        return (
            self.choose(
                "Confirm action",
                (
                    MenuOption("cancel", "Cancel"),
                    MenuOption("confirm", "Confirm"),
                ),
                context=message,
                columns=2,
            )
            == "confirm"
        )

    def show(self, text: str) -> None:
        """Display informational text through the injected line output."""
        if self._interactive and self._session_active:
            self._messages.append(text)
            return
        self._output_fn(text)

    def _message_window(self) -> Window:
        return Window(
            content=FormattedTextControl(lambda: ANSI("\n".join(self._messages))),
            height=Dimension(min=0, preferred=4 if self._messages else 0, max=8),
            wrap_lines=True,
            always_hide_cursor=True,
        )

    def _with_panel(self, body: HSplit) -> DynamicContainer | HSplit:
        if self._panel_renderer is None or self._output is None:
            return body

        def render_panel() -> ANSI:
            assert self._output is not None
            size = self._output.get_size()
            wide = size.columns >= 110
            width = 72 if wide else size.columns
            height = size.rows if wide else 14
            assert self._panel_renderer is not None
            return ANSI(self._panel_renderer(width, height))

        panel = Window(
            content=FormattedTextControl(render_panel),
            width=Dimension.exact(72),
            wrap_lines=False,
            always_hide_cursor=True,
        )
        wide_layout = VSplit([panel, body], padding=1)
        narrow_layout = HSplit(
            [
                Window(
                    content=panel.content,
                    height=Dimension.exact(14),
                    wrap_lines=False,
                    always_hide_cursor=True,
                ),
                body,
            ]
        )

        def responsive_layout() -> VSplit | HSplit:
            assert self._output is not None
            return wide_layout if self._output.get_size().columns >= 110 else narrow_layout

        return DynamicContainer(responsive_layout)

    def _choose_numbered(
        self,
        title: str,
        options: tuple[MenuOption, ...],
        context: str,
    ) -> str | None:
        lines = [title]
        if context:
            lines.append(context)
        for number, option in enumerate(options, 1):
            line = f"{number}. {option.label}"
            if option.disabled_reason:
                line += f" [disabled: {option.disabled_reason}]"
            lines.append(line)
            if option.details:
                lines.append(f"   {option.details}")
        self.show("\n".join(lines))

        while True:
            try:
                raw = self._input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt, StopIteration) as exc:
                raise TerminalClosed from exc
            if raw.lower() in {"", "back", "cancel", "\x1b", "\x08", "\x7f"}:
                return None
            try:
                index = int(raw) - 1
            except ValueError:
                self.show(f"Choose a number from 1 to {len(options)}, or cancel.")
                continue
            if not 0 <= index < len(options):
                self.show(f"Choose a number from 1 to {len(options)}, or cancel.")
                continue
            option = options[index]
            if option.disabled_reason:
                self.show(option.disabled_reason)
                continue
            return option.value

    def _choose_interactive(
        self,
        title: str,
        options: tuple[MenuOption, ...],
        context: str,
        columns: int,
    ) -> str | None:
        selected = 0
        notice = ""
        info_line = 0

        def effective_columns() -> int:
            if columns == 2 and self._output is not None:
                available = self._output.get_size().columns
                if self._panel_renderer is not None and available >= 110:
                    available -= 73
                return 1 if available < 80 else 2
            return columns

        def row_count() -> int:
            width = effective_columns()
            return (len(options) + width - 1) // width

        def render_options() -> StyleAndTextTuples:
            fragments: StyleAndTextTuples = []
            width = effective_columns()
            rows = row_count()
            cell_width = max(12, 38 if width == 2 else 1)
            for row in range(rows):
                for column in range(width):
                    index = row * width + column
                    if index >= len(options):
                        continue
                    option = options[index]
                    marker = "> " if index == selected else "  "
                    label = f"{index + 1}. {option.label}"
                    if option.disabled_reason:
                        label += f" [disabled: {option.disabled_reason}]"
                    text = marker + label
                    if width > 1 and column < width - 1:
                        text = text.ljust(cell_width)
                    style = "class:selected" if index == selected else ""
                    if option.disabled_reason:
                        style += " class:disabled"
                    fragments.append((style.strip(), text))
                fragments.append(("", "\n"))
            return fragments

        def cursor_position() -> Point:
            return Point(x=0, y=selected // effective_columns())

        def render_details() -> StyleAndTextTuples:
            fragments: StyleAndTextTuples = []
            if notice:
                fragments.extend(to_formatted_text(ANSI(notice), style="class:error"))
            if self._messages:
                if fragments:
                    fragments.append(("", "\n"))
                fragments.extend(
                    to_formatted_text(ANSI("\n".join(self._messages)), style="class:context")
                )
            if options[selected].details:
                if fragments:
                    fragments.append(("", "\n"))
                fragments.extend(
                    to_formatted_text(ANSI(options[selected].details), style="class:details")
                )
            if context:
                if fragments:
                    fragments.append(("", "\n"))
                fragments.extend(to_formatted_text(ANSI(context), style="class:context"))
            return fragments

        def wrapped_info_lines() -> list[StyleAndTextTuples]:
            terminal_width = self._output.get_size().columns if self._output is not None else 80
            if self._panel_renderer is not None and terminal_width >= 110:
                terminal_width -= 73
            width = max(1, terminal_width - 1)
            wrapped: list[StyleAndTextTuples] = []
            for logical_line in split_lines(render_details()):
                current: StyleAndTextTuples = []
                current_width = 0
                for fragment in logical_line:
                    style, fragment_text = fragment[:2]
                    for character in fragment_text:
                        character_width = get_cwidth(character)
                        if current and current_width + character_width > width:
                            wrapped.append(current)
                            current = []
                            current_width = 0
                        current.append((style, character))
                        current_width += character_width
                wrapped.append(current)
            return wrapped or [[]]

        def render_wrapped_details() -> StyleAndTextTuples:
            fragments: StyleAndTextTuples = []
            lines = wrapped_info_lines()
            for index, line in enumerate(lines):
                fragments.extend(line)
                if index + 1 < len(lines):
                    fragments.append(("", "\n"))
            return fragments

        def info_line_count() -> int:
            return len(wrapped_info_lines())

        def info_cursor_position() -> Point:
            return Point(x=0, y=min(info_line, info_line_count() - 1))

        control = FormattedTextControl(
            text=render_options,
            get_cursor_position=cursor_position,
            focusable=True,
            show_cursor=False,
        )
        header = f"{title}\n[PgUp/PgDn: info]"
        layout = HSplit(
            [
                Window(
                    content=FormattedTextControl(header),
                    height=2,
                    wrap_lines=True,
                    always_hide_cursor=True,
                ),
                Window(
                    content=control,
                    height=Dimension(min=1, preferred=min(row_count(), 10), max=10),
                    wrap_lines=False,
                    always_hide_cursor=True,
                ),
                Window(
                    content=FormattedTextControl(
                        render_wrapped_details,
                        get_cursor_position=info_cursor_position,
                    ),
                    height=Dimension(min=3, preferred=10),
                    wrap_lines=False,
                    always_hide_cursor=True,
                ),
            ]
        )
        bindings = KeyBindings()

        def move(delta: int) -> None:
            nonlocal info_line, selected, notice
            target = selected + delta
            if 0 <= target < len(options):
                selected = target
                info_line = 0
            notice = ""

        @bindings.add("pageup")
        def _page_up(event: KeyPressEvent) -> None:
            nonlocal info_line
            info_line = max(0, info_line - 4)
            event.app.invalidate()

        @bindings.add("pagedown")
        def _page_down(event: KeyPressEvent) -> None:
            nonlocal info_line
            info_line = min(info_line + 4, info_line_count() - 1)
            event.app.invalidate()

        @bindings.add("up")
        def _up(event: KeyPressEvent) -> None:
            move(-effective_columns())

        @bindings.add("down")
        def _down(event: KeyPressEvent) -> None:
            move(effective_columns())

        @bindings.add("left")
        def _left(event: KeyPressEvent) -> None:
            if effective_columns() == 2 and selected % 2 == 1:
                move(-1)

        @bindings.add("right")
        def _right(event: KeyPressEvent) -> None:
            if effective_columns() == 2 and selected % 2 == 0 and selected + 1 < len(options):
                move(1)

        def accept(event: KeyPressEvent, index: int | None = None) -> None:
            nonlocal selected, notice
            if index is not None:
                if index >= len(options):
                    return
                selected = index
            option = options[selected]
            if option.disabled_reason:
                notice = option.disabled_reason
                event.app.invalidate()
                return
            event.app.exit(result=option.value)

        @bindings.add("enter")
        @bindings.add(" ")
        def _accept(event: KeyPressEvent) -> None:
            accept(event)

        for number in range(1, min(9, len(options)) + 1):
            bindings.add(str(number))(lambda event, index=number - 1: accept(event, index))

        @bindings.add("escape", eager=True)
        @bindings.add("backspace")
        def _cancel(event: KeyPressEvent) -> None:
            event.app.exit(result=None)

        @bindings.add("c-c")
        @bindings.add("c-d")
        def _closed(event: KeyPressEvent) -> None:
            event.app.exit(exception=TerminalClosed())

        application: Application[str | None] = Application(
            layout=Layout(self._with_panel(layout), focused_element=control),
            key_bindings=bindings,
            full_screen=False,
            erase_when_done=self._session_active,
            input=self._input,
            output=self._output,
        )
        try:
            self._prepare_screen()
            result = application.run()
        except (EOFError, KeyboardInterrupt) as exc:
            raise TerminalClosed from exc
        self._messages.clear()
        return result
