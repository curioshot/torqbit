"""colors.py — CSS colour strings to QColor.

The headline case: Qt's SVG renderer draws *nothing at all* for a stroke
given as `rgba(r,g,b,a)`. Every icon on the `system` theme was invisible
because that theme's tokens are emitted in that form.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

from island import colors


def test_hex_roundtrips():
    c = colors.to_qcolor("#f2efe8")
    assert (c.red(), c.green(), c.blue()) == (0xf2, 0xef, 0xe8)


def test_rgba_keeps_its_alpha():
    """The old parser dropped alpha entirely."""
    c = colors.to_qcolor("rgba(216, 224, 238, 200)")
    assert (c.red(), c.green(), c.blue()) == (216, 224, 238)
    assert c.alpha() == 200


def test_rgb_defaults_to_opaque():
    assert colors.to_qcolor("rgb(1, 2, 3)").alpha() == 255


def test_percentage_channels():
    c = colors.to_qcolor("rgba(100%, 0%, 50%, 1.0)")
    assert (c.red(), c.green(), c.blue()) == (255, 0, 128)


def test_css_fraction_alpha_and_qt_byte_alpha_agree_on_opacity():
    """Qt writes alpha as 0..255; CSS proper writes 0..1. Both reach here."""
    assert colors.to_qcolor("rgba(0,0,0,0)").alpha() == 0
    assert colors.to_qcolor("rgba(0,0,0,1.0)").alpha() == 255
    assert colors.to_qcolor("rgba(0,0,0,0.0)").alpha() == 0
    assert colors.to_qcolor("rgba(0,0,0,128)").alpha() == 128


def test_transparent_is_transparent_not_black():
    """`transparent` used to resolve to #000000."""
    assert colors.to_qcolor("transparent").alpha() == 0


def test_named_colours():
    assert colors.to_qcolor("white") == QColor("white")
    assert colors.to_qcolor("black") == QColor("black")


def test_short_hex():
    assert colors.to_qcolor("#abc").name() == "#aabbcc"


def test_junk_falls_back_instead_of_going_black():
    """Black is almost never the intended ink on a dark card."""
    assert colors.to_qcolor("hsl(210, 40%, 60%)", "#ff00ff").name() == "#ff00ff"
    assert colors.to_qcolor(None, "#00ff00").name() == "#00ff00"
    assert colors.to_qcolor("", "#0000ff").name() == "#0000ff"


def test_to_hex_is_qss_safe():
    assert colors.to_hex("#f2efe8") == "#f2efe8"
    # Qt style sheets do not accept #aarrggbb, so alpha becomes rgba(...)
    assert colors.to_hex("rgba(0, 0, 0, 0.5)", keep_alpha=True).startswith("rgba(")


def test_to_hex_drops_alpha_by_default():
    assert colors.to_hex("rgba(10, 20, 30, 40)") == "#0a141e"


def test_ink_is_always_six_hex_digits():
    """SvgRenderer is handed this as `currentColor`; anything else can leave
    the icon undrawn."""
    for value in ("#abc", "rgba(216,224,238,200)", "white", "transparent",
                  "rgb(1,2,3)", None, "nonsense"):
        out = colors.ink(value)
        assert out.startswith("#") and len(out) == 7, (value, out)
