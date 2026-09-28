from __future__ import annotations

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from spacefleet.cli.terminal_ui import MenuOption, TerminalClosed, TerminalUI
from tests.terminal_ui_helpers import FakeTerminalUI, RecordingDummyOutput, SizedDummyOutput


class LifecycleOutput(RecordingDummyOutput):
    def __init__(self, *, columns: int = 80, rows: int = 24) -> None:
        super().__init__(columns=columns, rows=rows)
        self.entered = 0
        self.left = 0

    def enter_alternate_screen(self) -> None:
        self.entered += 1

    def quit_alternate_screen(self) -> None:
        self.left += 1


def test_numbered_fallback_rejects_disabled_then_accepts_enabled() -> None:
    lines = iter(["2", "1"])
    shown: list[str] = []
    ui = TerminalUI(input_fn=lambda _prompt: next(lines), output_fn=shown.append, interactive=False)
    options = [
        MenuOption("macro", "Macro-cannon", details="Strength 4"),
        MenuOption("lance", "Lance", disabled_reason="insufficient credits"),
    ]

    assert ui.choose("Fit weapon", options, context="Credits: 0") == "macro"
    rendered = "\n".join(shown)
    assert "Fit weapon" in rendered
    assert "Credits: 0" in rendered
    assert "Strength 4" in rendered
    assert "insufficient credits" in rendered


@pytest.mark.parametrize("answer", ["", "back", "cancel", "\x1b", "\x7f"])
def test_numbered_fallback_cancels(answer: str) -> None:
    ui = TerminalUI(input_fn=lambda _prompt: answer, interactive=False)

    assert ui.choose("Action", [MenuOption("a", "A")]) is None


def test_numbered_fallback_closure_raises_terminal_closed() -> None:
    def closed(_prompt: str) -> str:
        raise EOFError

    ui = TerminalUI(input_fn=closed, interactive=False)

    with pytest.raises(TerminalClosed):
        ui.choose("Action", [MenuOption("a", "A")])


def test_session_uses_one_alternate_screen_and_restores_it_after_error() -> None:
    output = LifecycleOutput()
    ui = TerminalUI(output=output, interactive=True)

    with pytest.raises(RuntimeError), ui.session(), ui.session():
        raise RuntimeError("boom")

    assert (output.entered, output.left) == (1, 1)


def test_suspended_flow_temporarily_leaves_and_reenters_screen() -> None:
    output = LifecycleOutput()
    ui = TerminalUI(output=output, interactive=True)

    with ui.session(), ui.suspended():
        pass

    assert (output.entered, output.left) == (2, 2)


@pytest.mark.parametrize(
    ("columns", "expected_size"),
    [(80, (80, 14)), (120, (72, 24))],
)
def test_scoped_panel_and_queued_messages_share_the_prompt_screen(
    columns: int,
    expected_size: tuple[int, int],
) -> None:
    output = LifecycleOutput(columns=columns)
    sizes: list[tuple[int, int]] = []

    def panel(width: int, height: int) -> str:
        sizes.append((width, height))
        return "SCANNER PANEL"

    with create_pipe_input() as pipe:
        pipe.send_text("\r")
        ui = TerminalUI(input=pipe, output=output, interactive=True)
        with ui.session(), ui.panel(panel):
            ui.show("First report")
            ui.show("Second report")
            assert ui.choose("Action", [MenuOption("a", "A")]) == "a"

    rendered = "".join(output.writes)
    assert "SCANNER PANEL" in rendered
    assert "First report" in rendered
    assert "Second report" in rendered
    assert expected_size in sizes


def test_text_prompt_keeps_scoped_panel_visible() -> None:
    output = LifecycleOutput()
    with create_pipe_input() as pipe:
        pipe.send_text("90\r")
        ui = TerminalUI(input=pipe, output=output, interactive=True)
        with ui.session(), ui.panel(lambda _width, _height: "SCANNER PANEL"):
            assert ui.text("Bearing", "bearing") == "90"

    rendered = "".join(output.writes)
    assert "SCANNER PANEL" in rendered
    assert "Bearing" in rendered


def test_interactive_choose_focuses_but_rejects_disabled() -> None:
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b[B \x1b[B ")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)
        options = [
            MenuOption("a", "A"),
            MenuOption("b", "B", disabled_reason="locked"),
            MenuOption("c", "C"),
        ]

        assert ui.choose("Action", options) == "c"


@pytest.mark.parametrize("reject_key", ["\r", " ", "1"])
def test_interactive_choose_rejects_disabled_for_every_accept_key(reject_key: str) -> None:
    with create_pipe_input() as pipe:
        pipe.send_text(reject_key + "\x1b[B\r")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)
        options = [
            MenuOption("locked", "Locked", disabled_reason="not available"),
            MenuOption("ready", "Ready"),
        ]

        assert ui.choose("Action", options) == "ready"


def test_interactive_choose_supports_cancel_and_number_shortcuts() -> None:
    with create_pipe_input() as pipe:
        pipe.send_text("2")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)
        assert ui.choose("Action", [MenuOption("a", "A"), MenuOption("b", "B")]) == "b"

    with create_pipe_input() as pipe:
        pipe.send_text("\x7f")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)
        assert ui.choose("Action", [MenuOption("a", "A")]) is None


def test_interactive_choose_navigates_long_list() -> None:
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b[B" * 19 + "\r")
        ui = TerminalUI(
            input=pipe,
            output=SizedDummyOutput(columns=80, rows=8),
            interactive=True,
        )

        assert ui.choose("Long", [MenuOption(str(i), f"Option {i}") for i in range(20)]) == "19"


def test_interactive_choose_can_scroll_all_context_and_details() -> None:
    context = "\n".join(f"Context {number}" for number in range(7))
    details = "\n".join(f"Detail {number}" for number in range(7))
    rendered = ""
    for page_count, expected in ((2, "Detail 6"), (4, "Context 6")):
        output = RecordingDummyOutput(rows=10)
        with create_pipe_input() as pipe:
            pipe.send_text("\x1b[6~" * page_count + "\r")
            ui = TerminalUI(input=pipe, output=output, interactive=True)

            assert ui.choose("Action", [MenuOption("a", "A", details)], context=context) == "a"

        current_render = "".join(output.writes)
        assert expected in current_render
        rendered += current_render

    assert "PgUp/PgDn" in rendered


def test_interactive_choose_wraps_and_pages_a_long_detail_in_narrow_output() -> None:
    output = RecordingDummyOutput(columns=20, rows=10)
    details = "A long registry description that must wrap instead of disappearing. FINAL-MARKER"
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b[6~" * 20 + "\r")
        ui = TerminalUI(input=pipe, output=output, interactive=True)

        assert ui.choose("Action", [MenuOption("a", "A", details)]) == "a"

    assert "FINAL-MARKER" in "".join(output.writes).replace("\r\n", "")


def test_short_menu_shows_selected_details_before_long_context() -> None:
    output = RecordingDummyOutput(columns=60, rows=14)
    context = "\n".join(f"Context {number}" for number in range(20))
    with create_pipe_input() as pipe:
        pipe.send_text("\r")
        ui = TerminalUI(input=pipe, output=output, interactive=True)

        assert ui.choose("Weapon", [MenuOption("a", "A", "PRICE AND DESCRIPTION")], context) == "a"

    rendered = "".join(output.writes)
    assert "PRICE AND DESCRIPTION" in rendered
    assert "Context 0" in rendered


def test_two_column_navigation_and_narrow_fallback() -> None:
    options = [MenuOption(str(i), str(i)) for i in range(4)]
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b[C\x1b[B\r")
        ui = TerminalUI(input=pipe, output=SizedDummyOutput(columns=100), interactive=True)
        assert ui.choose("Grid", options, columns=2) == "3"

    with create_pipe_input() as pipe:
        pipe.send_text("\x1b[B\r")
        ui = TerminalUI(input=pipe, output=SizedDummyOutput(columns=79), interactive=True)
        assert ui.choose("Grid", options, columns=2) == "1"


def test_text_histories_are_separate_and_preserve_editing_buffer() -> None:
    with create_pipe_input() as pipe:
        pipe.send_text("Alpha Fleet\r19\r\x1b[A\x7fs\r")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)

        assert ui.text("Fleet name", "name") == "Alpha Fleet"
        assert ui.text("Seed", "seed") == "19"
        assert ui.text("Fleet name", "name") == "Alpha Flees"


def test_text_history_restores_live_draft_after_navigating_down() -> None:
    with create_pipe_input() as pipe:
        pipe.send_text("Previous\rDraft\x1b[A\x1b[B\r")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)

        assert ui.text("Name", "name") == "Previous"
        assert ui.text("Name", "name") == "Draft"


def test_text_escape_cancels_and_control_d_closes() -> None:
    with create_pipe_input() as pipe:
        pipe.send_text("draft\x1b")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)
        assert ui.text("Name", "name") is None

    with create_pipe_input() as pipe:
        pipe.send_text("\x04")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)
        with pytest.raises(TerminalClosed):
            ui.text("Name", "name")


def test_confirmation_starts_on_safe_choice() -> None:
    with create_pipe_input() as pipe:
        pipe.send_text("\r")
        ui = TerminalUI(input=pipe, output=DummyOutput(), interactive=True)
        assert ui.confirm("Delete save?") is False


def test_multiline_confirmation_uses_scrollable_context() -> None:
    calls: list[tuple[str, str]] = []

    class RecordingUI(TerminalUI):
        def choose(  # type: ignore[override]
            self,
            title,
            options,
            context="",
            columns=1,  # type: ignore[no-untyped-def]
        ) -> str | None:
            calls.append((title, context))
            return "cancel"

    message = "Price 10\nRefund 4\nNet charge 6\nResulting balance 94"

    assert RecordingUI(interactive=False).confirm(message) is False
    assert calls == [("Confirm action", message)]


def test_fake_terminal_ui_records_calls() -> None:
    fake = FakeTerminalUI(choices=["a"], texts=["name"], confirmations=[True])
    options = [MenuOption("a", "A")]

    assert fake.choose("Action", options, context="Context", columns=2) == "a"
    assert fake.text("Name", "fleet.name", "Default") == "name"
    assert fake.confirm("Proceed?") is True
    fake.show("Done")

    assert fake.choose_calls == [("Action", tuple(options), "Context", 2)]
    assert fake.text_calls == [("Name", "fleet.name", "Default")]
    assert fake.confirm_calls == ["Proceed?"]
    assert fake.show_calls == ["Done"]
