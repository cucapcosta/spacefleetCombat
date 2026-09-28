"""Tests for the braille raster canvas."""

from __future__ import annotations

from spacefleet.tui.model.raster import BrailleCanvas


def _lit(canvas: BrailleCanvas) -> set[tuple[int, int]]:
    """Decode the rendered braille back into lit dot coordinates."""
    left = (0x01, 0x02, 0x04, 0x40)
    right = (0x08, 0x10, 0x20, 0x80)
    dots: set[tuple[int, int]] = set()
    for row, text in enumerate(canvas.render()):
        for col, ch in enumerate(text.plain):
            if ch == " ":
                continue
            bits = ord(ch) - 0x2800
            for i in range(4):
                if bits & left[i]:
                    dots.add((col * 2, row * 4 + i))
                if bits & right[i]:
                    dots.add((col * 2 + 1, row * 4 + i))
    return dots


def test_empty_canvas_renders_spaces() -> None:
    rows = BrailleCanvas(3, 2).render()
    assert [r.plain for r in rows] == ["   ", "   "]


def test_set_dot_lights_correct_bit() -> None:
    c = BrailleCanvas(2, 1)
    c.set_dot(0, 0)
    c.set_dot(3, 3)  # cell 1, right column, bottom row -> 0x80
    assert c.render()[0].plain == chr(0x2801) + chr(0x2880)


def test_set_dot_out_of_bounds_ignored() -> None:
    c = BrailleCanvas(2, 1)
    c.set_dot(-1, 0)
    c.set_dot(4, 0)
    c.set_dot(0, 4)
    assert _lit(c) == set()


def test_diagonal_line() -> None:
    c = BrailleCanvas(4, 1)
    c.line(0, 0, 3, 3, "red")
    assert _lit(c) == {(0, 0), (1, 1), (2, 2), (3, 3)}


def test_dashed_line_skips_dots() -> None:
    c = BrailleCanvas(10, 1)
    c.line(0, 0, 19, 0, "red", dashed=True)
    lit = _lit(c)
    assert 0 < len(lit) < 20


def test_style_last_written_wins() -> None:
    c = BrailleCanvas(1, 1)
    c.set_dot(0, 0, "red")
    c.set_dot(1, 1, "blue")
    assert str(c.render()[0].spans[0].style) == "blue"


def test_sector_never_out_of_bounds() -> None:
    c = BrailleCanvas(5, 3)
    c.sector(2, 2, 40, 0, 270, "green")  # radius far exceeds the canvas
    assert all(len(r.plain) == 5 for r in c.render())
    assert len(c.render()) == 3


def test_circle_is_symmetric() -> None:
    c = BrailleCanvas(10, 5)
    c.circle(10, 10, 6, "cyan")
    lit = _lit(c)
    assert (10, 4) in lit and (10, 16) in lit and (4, 10) in lit and (16, 10) in lit


def test_north_arc_point_is_above_center() -> None:
    c = BrailleCanvas(10, 5)
    c.arc(10, 10, 6, -10, 10, "red")
    lit = _lit(c)
    assert (10, 4) in lit
    assert all(y < 10 for _, y in lit)


def test_east_arc_point_is_right_of_center() -> None:
    c = BrailleCanvas(10, 5)
    c.arc(10, 10, 6, 80, 100, "red")
    lit = _lit(c)
    assert (16, 10) in lit
    assert all(x > 10 for x, _ in lit)


def test_arc_wrapping_through_north() -> None:
    c = BrailleCanvas(10, 5)
    c.arc(10, 10, 6, 350, 10, "red")
    lit = _lit(c)
    assert (10, 4) in lit
    assert all(y < 10 for _, y in lit)


def test_put_text_overrides_dots() -> None:
    c = BrailleCanvas(4, 1)
    c.line(0, 0, 7, 0, "red")
    c.put_text(1, 0, "AB", "bold")
    row = c.render()[0]
    assert row.plain[1:3] == "AB"
    assert row.plain[0] != " " and row.plain[3] != " "


def test_put_text_clipped_at_edge() -> None:
    c = BrailleCanvas(3, 1)
    c.put_text(2, 0, "XYZ", None)
    c.put_text(0, 5, "Q", None)
    assert c.render()[0].plain == "  X"
