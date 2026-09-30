"""Ship side-profile art: hull ``art:`` lines to styled Rich text (pure, no Textual)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from spacefleet.core.types import Faction, ShipClass

if TYPE_CHECKING:
    from spacefleet.models.ship_profile import HullProfile

HULL_CHARS = frozenset("█▄▀")
ARMOUR_CHAR = "▓"
GLOW_CHARS = frozenset("◀▶")
ALLOWED_CHARS = HULL_CHARS | GLOW_CHARS | {ARMOUR_CHAR, " "}

ART_WIDTH_RANGE: dict[ShipClass, tuple[int, int]] = {
    ShipClass.ESCORT: (10, 14),
    ShipClass.LIGHT_CRUISER: (15, 20),
    ShipClass.CRUISER: (20, 26),
    ShipClass.BATTLECRUISER: (24, 30),
    ShipClass.BATTLESHIP: (30, 36),
}

ART_HEIGHT_RANGE: dict[ShipClass, tuple[int, int]] = {
    ShipClass.ESCORT: (3, 3),
    ShipClass.LIGHT_CRUISER: (3, 4),
    ShipClass.CRUISER: (4, 4),
    ShipClass.BATTLECRUISER: (4, 5),
    ShipClass.BATTLESHIP: (5, 5),
}

# Hull colour per faction; armour (``▓``) and engine glow (``◀▶``) tones below.
FACTION_STYLE: dict[Faction, str] = {
    Faction.IMPERIAL_NAVY: "#c8d0e0",
    Faction.CHAOS_FLEET: "#c0283c",
}
ARMOUR_STYLE: dict[Faction, str] = {
    Faction.IMPERIAL_NAVY: "#6c7690",
    Faction.CHAOS_FLEET: "#6a1420",
}
GLOW_STYLE: dict[Faction, str] = {
    Faction.IMPERIAL_NAVY: "bright_cyan",
    Faction.CHAOS_FLEET: "orange1",
}
DAMAGE_STYLE = "red1"
_DEFAULT_HULL = "white"


def art_lines(hull: HullProfile) -> tuple[str, ...]:
    """The hull's art padded to equal width, or a generic block for its class."""
    lines = hull.art or _fallback(hull.classification)
    width = max(len(line) for line in lines)
    return tuple(line.ljust(width) for line in lines)


def _fallback(ship_class: ShipClass) -> tuple[str, ...]:
    low, high = ART_WIDTH_RANGE[ship_class]
    width = (low + high) // 2
    height = ART_HEIGHT_RANGE[ship_class][0]
    top = "  " + "▄" * (width // 2)
    middle = "◀▓" + "█" * (width - 3) + "▶"
    bottom = "  " + "▀" * (width - 5)
    return (top, *([middle] * (height - 2)), bottom)


def _scramble(row: int, col: int) -> int:
    """Deterministic pseudo-random key used to spread damage over the hull."""
    value = (row * 73856093) ^ (col * 19349663)
    value = (value ^ (value >> 13)) * 0x5BD1E995
    return (value ^ (value >> 15)) & 0xFFFFFFFF


def damaged_cells(lines: tuple[str, ...], damage_ratio: float) -> set[tuple[int, int]]:
    """The (row, col) hull cells shown as damaged for *damage_ratio* (clamped 0..1)."""
    ratio = min(max(damage_ratio, 0.0), 1.0)
    cells = [
        (row, col)
        for row, line in enumerate(lines)
        for col, char in enumerate(line)
        if char in HULL_CHARS
    ]
    cells.sort(key=lambda cell: (_scramble(*cell), cell))
    return set(cells[: round(ratio * len(cells))])


def render_art(
    hull: HullProfile, *, damage_ratio: float = 0.0, selected: bool = False
) -> list[Text]:
    """One Rich ``Text`` per art line with a per-character style."""
    lines = art_lines(hull)
    damaged = damaged_cells(lines, damage_ratio)
    hull_style = FACTION_STYLE.get(hull.faction, _DEFAULT_HULL)
    armour_style = ARMOUR_STYLE.get(hull.faction, "grey50")
    glow_style = GLOW_STYLE.get(hull.faction, "bright_white")
    emphasis = " bold" if selected else ""
    result: list[Text] = []
    for row, line in enumerate(lines):
        text = Text()
        for col, char in enumerate(line):
            if char == " ":
                text.append(char)
            elif (row, col) in damaged:
                text.append(ARMOUR_CHAR, style=DAMAGE_STYLE + emphasis)
            elif char in HULL_CHARS:
                text.append(char, style=hull_style + emphasis)
            elif char in GLOW_CHARS:
                text.append(char, style=glow_style + emphasis)
            else:
                text.append(char, style=armour_style + emphasis)
        result.append(text)
    return result
