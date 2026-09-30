"""Title screen: block-letter banner, an Imperial and a Chaos ship, and the main menu.

::

    ┌──────────────────────────────────────────┬ #menu (32) ─┐
    │  SPACEFLEET / COMBAT banner              │ Campaign    │
    │  Campaign Edition v0.2                   │ Connect ... │
    │  Imperial ship ▶        ◀ Chaos ship     │ Fleet ...   │
    │                                          │ Quit        │
    └ footer ──────────────────────────────────┴─────────────┘

The menu asks the app to open each screen (``open_campaign``, ``open_connect``,
``open_fleet_builder``); Quit dismisses the title, which ends the app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol

from rich.style import Style
from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from spacefleet.data.hull_registry import HullRegistry
from spacefleet.tui.model.ship_art import render_art

if TYPE_CHECKING:
    from textual.app import ComposeResult

VERSION = "Campaign Edition v0.2"
IMPERIAL_HULL = "emperor_battleship"
CHAOS_HULL = "desolator_battleship"

# Two-row half-block font for the banner letters.
_FONT: dict[str, tuple[str, str]] = {
    "A": ("▄▀█", "█▀█"),
    "B": ("█▄▄", "█▄█"),
    "C": ("█▀▀", "█▄▄"),
    "E": ("█▀▀", "██▄"),
    "F": ("█▀▀", "█▀ "),
    "L": ("█  ", "█▄▄"),
    "M": ("█▀▄▀█", "█ ▀ █"),
    "O": ("█▀█", "█▄█"),
    "P": ("█▀█", "█▀▀"),
    "S": ("█▀▀", "▄▄█"),
    "T": ("▀█▀", " █ "),
    " ": ("  ", "  "),
}

MENU: tuple[tuple[str, str], ...] = (
    ("campaign", "Campaign"),
    ("connect", "Connect to Server"),
    ("fleet", "Fleet Builder"),
    ("quit", "Quit"),
)
_MENU_KEYS = {"campaign": "C", "connect": "O", "fleet": "F", "quit": "Q"}


class TitleHost(Protocol):
    """What the title needs from its app (see :class:`SpacefleetApp`)."""

    def open_campaign(self) -> None: ...
    def open_connect(self) -> None: ...
    def open_fleet_builder(self) -> None: ...


def banner(word: str) -> list[str]:
    """*word* in the two-row block font (unknown characters become blanks)."""
    rows = ["", ""]
    for char in word.upper():
        top, bottom = _FONT.get(char, _FONT[" "])
        rows[0] += top + " "
        rows[1] += bottom + " "
    return [row[:-1] for row in rows]


def title_block() -> str:
    """``SPACEFLEET`` over ``COMBAT``, each word centred in a block of equal-width lines."""
    lines = [*banner("SPACEFLEET"), "", *banner("COMBAT")]
    width = max(len(line) for line in lines)
    return "\n".join(line.center(width) for line in lines)


def mirror(line: Text) -> Text:
    """*line* flipped left-right, keeping each character's style.

    Block characters are symmetric; only the ``◀``/``▶`` glyphs swap.
    """
    swap = {"◀": "▶", "▶": "◀"}
    plain = line.plain
    styles: list[list[str | Style]] = [[line.style] if line.style else [] for _ in plain]
    for span in line.spans:
        for index in range(span.start, min(span.end, len(plain))):
            styles[index].append(span.style)
    result = Text()
    for index in range(len(plain) - 1, -1, -1):
        char = plain[index]
        parts = [Style.parse(s) if isinstance(s, str) else s for s in styles[index]]
        style = Style.chain(*parts) if parts else Style.null()
        result.append(swap.get(char, char), style=style)
    return result


def duel_art(gap: int = 6) -> Text:
    """The Imperial ship (prow right) facing the Chaos ship (mirrored, prow left)."""
    imperial = render_art(HullRegistry.get(IMPERIAL_HULL))
    chaos = [mirror(line) for line in render_art(HullRegistry.get(CHAOS_HULL))]
    height = max(len(imperial), len(chaos))
    left_width = max(len(line) for line in imperial)
    right_width = max(len(line) for line in chaos)
    top_left = (height - len(imperial)) // 2
    top_right = (height - len(chaos)) // 2
    rows: list[Text] = []
    for row in range(height):
        left_index = row - top_left
        right_index = row - top_right
        left = imperial[left_index] if 0 <= left_index < len(imperial) else Text()
        right = chaos[right_index] if 0 <= right_index < len(chaos) else Text()
        line = left.copy()
        line.pad_right(left_width - len(left))
        line.append(" " * gap)
        right = right.copy()
        right.pad_right(right_width - len(right))
        line.append_text(right)
        rows.append(line)
    return Text("\n").join(rows)


class TitleScreen(Screen[None]):
    """Main menu. Dismissed (with ``None``) when the player quits."""

    DEFAULT_CSS = """
    TitleScreen #body { height: 1fr; }
    TitleScreen #main { width: 1fr; height: 1fr; align: center middle; }
    TitleScreen #main > Static { width: 100%; text-align: center; }
    TitleScreen #banner { color: $accent; text-style: bold; height: auto; }
    TitleScreen #version { color: $text-muted; height: 1; margin-bottom: 2; }
    TitleScreen #art { height: auto; }
    TitleScreen #motto { color: $text-muted; height: 1; margin-top: 2; }
    TitleScreen #side {
        width: 32; height: 1fr; border-left: solid $primary; padding: 1 1;
        align: left middle;
    }
    TitleScreen #menu-title { text-style: bold; margin-bottom: 1; }
    TitleScreen #menu { height: auto; border: none; }
    TitleScreen #hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("c", "choose('campaign')", "Campaign"),
        Binding("o", "choose('connect')", "Connect"),
        Binding("f", "choose('fleet')", "Fleet Builder"),
        Binding("q", "choose('quit')", "Quit"),
        Binding("ctrl+q,ctrl+c", "choose('quit')", "Quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="main"):
                yield Static(title_block(), id="banner", markup=False)
                yield Static(VERSION, id="version", markup=False)
                yield Static(duel_art(), id="art")
                yield Static("In the grim darkness of the far future...", id="motto")
            with Vertical(id="side"):
                yield Static("Main Menu", id="menu-title", markup=False)
                yield OptionList(
                    *(Option(f"[{_MENU_KEYS[key]}] {label}", id=key) for key, label in MENU),
                    id="menu",
                    markup=False,
                )
                yield Static("↑/↓ + Enter or letter keys", id="hint", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        menu = self.query_one("#menu", OptionList)
        menu.highlighted = 0
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id is not None:
            self.action_choose(event.option.id)

    def action_choose(self, choice: str) -> None:
        if choice == "quit":
            self.dismiss(None)
            return
        host: TitleHost = self.app  # type: ignore[assignment]
        if choice == "campaign":
            host.open_campaign()
        elif choice == "connect":
            host.open_connect()
        elif choice == "fleet":
            host.open_fleet_builder()
