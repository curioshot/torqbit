"""Geometry shared between the window and anything that positions itself
relative to the island.

These used to be module constants in window.py and then hard-coded a second
time inside services.py (252 / 42 / 8). Changing the island width silently
moved the Spotify overlay somewhere wrong, because nothing linked the two.

Deliberately Qt-free so any module can import it without a QApplication.
"""

# Collapsed top-screen capsule.
COLLAPSED_ISLAND_W = 252
COLLAPSED_ISLAND_H = 42

# Collapsed corner quarter-circle.
COLLAPSED_CORNER = 112

# Expanded card.
EXPANDED_W = 400
EXPANDED_H = 560
# Upper bound when a tab asks for more room than the default height. Past
# this the card would cover most of a laptop screen for no gain.
EXPANDED_MAX_H = 660

# Control rail (sliders + toggle grid) living inside the expanded card,
# left of the tab content. Qt-free like the rest of this module; center.py
# re-exports these names (tests import them from island.center).
# The grid invariant: RAIL_W >= 4*DOT_W + 3*DOT_GAP, so a dot never wraps.
RAIL_COLUMNS = 4
DOT_W, DOT_H = 48, 60
DOT_GAP = 10
SLIDER_W = 56
RAIL_W = RAIL_COLUMNS * DOT_W + (RAIL_COLUMNS - 1) * DOT_GAP  # 222

# Inset from the top of the available screen area.
ISLAND_TOP_INSET = 8

# Gap between the card and the control-centre panel below it.
CENTRE_GAP = 8

# Full expanded-card width: tab column + rail + the gap between them.
# The rail is hidden in corner mode, but the card keeps one width
# everywhere so geometry never drifts between modes.
CARD_W = EXPANDED_W + RAIL_W + CENTRE_GAP  # 630

# The control-centre rail sits immediately left of the card.
CENTRE_W = 1120
CENTRE_H = 360
CENTRE_MIN_W = 920
CENTRE_MIN_H = 240