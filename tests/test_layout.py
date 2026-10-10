"""The three-state layout: collapsed pill, expanded card, full island.

The full island is one row (rail beside the panel), replacing the old two-row
stacking where the card sat above the panel and the rail had to be
re-parented between two layouts.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BOT_ISLAND_NO_WEBENGINE", "1")


@pytest.fixture
def window(qapp, cfg_home, monkeypatch):
    from island import config as cfgmod
    from island.window import IslandWindow
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", cfg_home.CONFIG_DIR)
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", cfg_home.CONFIG_FILE)
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", cfg_home.EVENTS_FILE)
    monkeypatch.setattr(cfgmod, "NOTES_FILE", cfg_home.NOTES_FILE)
    w = IslandWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    qapp.processEvents()


def settle(qapp):
    from PySide6.QtTest import QTest
    QTest.qWait(600)
    qapp.processEvents()


# ---------------------------------------------------------------- states
def test_three_states_are_mutually_exclusive(window, qapp):
    """At any moment exactly one of these is on screen."""
    def visible():
        return [n for n in ("collapsed", "card", "center")
                if not getattr(window, n).isHidden()]

    settle(qapp)
    assert visible() == ["collapsed"]

    window.expand()
    settle(qapp)
    assert visible() == ["card"]

    window.open_centre()
    settle(qapp)
    assert visible() == ["center"]

    window.close_centre()
    settle(qapp)
    assert visible() == ["card"]

    window.collapse()
    settle(qapp)
    assert visible() == ["collapsed"]


def test_rail_is_present_in_both_wide_states(window, qapp):
    settle(qapp)
    assert window.rail.isHidden()
    window.expand()
    settle(qapp)
    assert not window.rail.isHidden()
    window.open_centre()
    settle(qapp)
    assert not window.rail.isHidden()
    # Collapse steps back one level at a time: full -> card -> pill.
    window.collapse()
    settle(qapp)
    assert not window.rail.isHidden(), "rail belongs in the card state too"
    window.collapse()
    settle(qapp)
    assert window.rail.isHidden()


def test_rail_is_hidden_in_corner_mode(window, qapp):
    """In corner mode there is nothing beside the rail to control."""
    window._set_mode("corner")
    settle(qapp)
    window.expand()
    settle(qapp)
    assert window.rail.isHidden()
    # ...but the full island still needs it.
    window.open_centre()
    settle(qapp)
    assert not window.rail.isHidden()


# -------------------------------------------------------------- geometry
def test_expanded_window_fits_the_rail_beside_the_card(window, qapp):
    """Sizing the window to EXPANDED_W left a 172px rail crammed into a
    368px window."""
    from island.geom import CENTRE_GAP, EXPANDED_W
    window.expand()
    settle(qapp)
    assert window.width() == EXPANDED_W + window.rail.width() + CENTRE_GAP
    assert window.card.width() == EXPANDED_W


def test_collapsed_window_is_exactly_the_pill(window, qapp):
    from island.geom import COLLAPSED_ISLAND_H, COLLAPSED_ISLAND_W
    settle(qapp)
    assert window.size().width() == COLLAPSED_ISLAND_W
    assert window.size().height() == COLLAPSED_ISLAND_H


def test_full_panel_height_equals_the_window_height(window, qapp):
    """The old layout added card + gap + panel, so the panel was shorter
    than the window. Now they are the same."""
    window.open_centre()
    settle(qapp)
    assert window.height() == window.center.height()


def test_card_height_is_bounded(window, qapp):
    from island.geom import EXPANDED_H, EXPANDED_MAX_H
    window.expand()
    settle(qapp)
    assert window.card.height() <= EXPANDED_MAX_H
    assert window.card.height() >= EXPANDED_H


def test_states_round_trip_without_drift(window, qapp):
    """Walk the transitions twice; the geometry must come back identical."""
    window.expand()
    settle(qapp)
    first = window.size()
    for _ in range(2):
        window.open_centre()
        settle(qapp)
        window.close_centre()
        settle(qapp)
    assert window.size() == first, "geometry drifted over repeated toggles"


# -------------------------------------------------------------- contents
def test_full_panel_has_feeds_gauge_and_calendar(window, qapp):
    window.open_centre()
    settle(qapp)
    centre = window.center
    for name in ("feeds", "gauge", "calendar"):
        assert hasattr(centre, name), f"{name} missing from the full panel"
    # All three must actually be laid out, not just constructed.
    assert centre.feeds.width() > 0
    assert centre.gauge.width() > 0
    assert centre.calendar.width() > 0


def test_column_widths_do_not_collapse(window, qapp):
    window.open_centre()
    settle(qapp)
    centre = window.center
    assert centre.gauge.width() >= 150
    assert centre.calendar.width() >= 200
    assert centre.feeds.width() >= centre.gauge.width()


# --------------------------------------------------------------- to-dos
def test_todo_column_adds_and_removes(qapp, cfg_home, monkeypatch):
    from island import config as cfgmod
    from island.todo import TodoColumn
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", cfg_home.CONFIG_FILE)
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", cfg_home.EVENTS_FILE)
    col = TodoColumn()
    col.reload()

    col.input.setText("buy milk")
    col.add_item()
    assert cfgmod.load_events()[col._key()] == ["buy milk"]

    col.list.setCurrentRow(0)
    col.remove_selected()
    assert col._key() not in cfgmod.load_events()


def test_todo_column_does_not_clobber_the_card_tab(qapp, cfg_home,
                                                   monkeypatch):
    """Both write the same events file. Each must re-read before mutating,
    or the second writer silently discards the first's edits."""
    from island import config as cfgmod
    from island.todo import TodoColumn
    from island.tabs import CalendarTab
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", cfg_home.CONFIG_FILE)
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", cfg_home.EVENTS_FILE)

    card_tab = CalendarTab()
    card_tab.reload = lambda: None      # hold its copy open, as a live tab would
    card_tab.input.setText("from the card")
    card_tab.add_event()
    card_tab.events.setdefault(card_tab._date_key(), []).append("stale copy")

    col = TodoColumn()
    col.input.setText("from the panel")
    col.add_item()

    stored = cfgmod.load_events()[col._key()]
    assert "from the card" in stored, "the panel column discarded the card's event"
    assert "from the panel" in stored


def test_todo_column_month_navigation(qapp, cfg_home, monkeypatch):
    from island import config as cfgmod
    from island.todo import TodoColumn
    from PySide6.QtCore import QDate
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", cfg_home.EVENTS_FILE)
    col = TodoColumn()
    col.cal.setSelectedDate(QDate(2026, 3, 15))
    before = col.cal.selectedDate()
    col._next_month()
    after = col.cal.selectedDate()
    assert after.month() == (before.month() % 12) + 1
    col._prev_month()
    assert col.cal.selectedDate().month() == before.month()
