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
EXPANDED_W = 368
EXPANDED_H = 540
# Upper bound when a tab asks for more room than the default height. Past
# this the card would cover most of a laptop screen for no gain.
EXPANDED_MAX_H = 660

# Inset from the top of the available screen area.
ISLAND_TOP_INSET = 8

# Gap between the card and the control-centre panel below it.
CENTRE_GAP = 8

# The control-centre rail sits immediately left of the card.
CENTRE_W = 1120
CENTRE_H = 300
CENTRE_MIN_W = 900
CENTRE_MIN_H = 190