"""The calendar / to-dos column of the full island.

Deliberately not a second copy of the card's CalendarTab: both read the
same events file, and a naive second instance would hold its own in-memory
copy and silently overwrite the other's edits. This column re-reads from
config before every mutation instead.

It is also a different shape on purpose. In the card the calendar gets a
full tab; here it is one narrow column beside the RSS list, so it shows a
compact month grid and the selected day's items.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCalendarWidget,
    QListWidget, QListWidgetItem, QLineEdit, QGridLayout,
)

from . import config as cfgmod

CALENDAR_W = 260
MONTH_FMT = "d MMM yyyy"


class TodoColumn(QWidget):
    """Compact calendar plus the selected day's items."""

    changed = Signal()

    def __init__(self, on_config_changed=None, parent=None):
        super().__init__(parent)
        self._on_cfg = on_config_changed
        self._pal: dict = {}
        self._events: dict[str, list[str]] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        title = QLabel("To-dos")
        title.setStyleSheet("font-size: 12px; font-weight: 700;")
        title.setAccessibleName("Calendar and to-dos")
        lay.addWidget(title)

        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        # A full QCalendarWidget in a 260px column is unreadable; the
        # navigation bar alone eats a third of it.
        self.cal.setNavigationBarVisible(False)
        self.cal.setFixedHeight(168)
        self.cal.setAccessibleName("Date picker")
        lay.addWidget(self.cal)

        self.month = QLabel()
        self.month.setAccessibleName("Selected month")
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        prev = QPushButton("‹")
        nxt = QPushButton("›")
        for b, tip in ((prev, "Previous month"), (nxt, "Next month")):
            b.setFixedSize(24, 24)
            b.setFlat(True)
            b.setAccessibleName(tip)
            b.setToolTip(tip)
        prev.clicked.connect(self._prev_month)
        nxt.clicked.connect(self._next_month)
        head.addWidget(prev)
        head.addWidget(self.month, 1)
        head.addWidget(nxt)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.setAccessibleName("Items on the selected date")
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Add… (Enter)")
        self.input.setAccessibleName("New to-do")
        self.input.returnPressed.connect(self.add_item)
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedWidth(28)
        self.add_btn.setAccessibleName("Add this to-do")
        self.add_btn.clicked.connect(self.add_item)
        self.del_btn = QPushButton("−")
        self.del_btn.setFixedWidth(28)
        self.del_btn.setAccessibleName("Remove the selected to-do")
        self.del_btn.clicked.connect(self.remove_selected)
        row.addWidget(self.input, 1)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        lay.addLayout(row)

        self.cal.selectionChanged.connect(self.refresh)
        self.reload()

    # ------------------------------------------------------------------
    def _key(self) -> str:
        return self.cal.selectedDate().toString("yyyy-MM-dd")

    def reload(self) -> None:
        """Re-read from disk.

        The card's CalendarTab holds its own copy of the same file. Reading
        fresh before every mutation is what stops the two from clobbering
        each other's edits.
        """
        self._events = cfgmod.load_events()
        self.refresh()

    def refresh(self) -> None:
        self.month.setText(self.cal.selectedDate().toString(MONTH_FMT))
        items = self._events.get(self._key(), [])
        self.list.clear()
        for text in items:
            self.list.addItem(text)
        self.del_btn.setEnabled(bool(items))
        if not items:
            item = QListWidgetItem("Nothing on this day")
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(QBrush(QColor(130, 130, 140)))
            self.list.addItem(item)

    # ------------------------------------------------------------------
    def _prev_month(self) -> None:
        d = self.cal.selectedDate().addMonths(-1)
        self.cal.setSelectedDate(QDate(d.year(), d.month(), 1))
        self._sync_navigation()

    def _next_month(self) -> None:
        d = self.cal.selectedDate().addMonths(1)
        self.cal.setSelectedDate(QDate(d.year(), d.month(), 1))
        self._sync_navigation()

    def _sync_navigation(self) -> None:
        """Keep the grid and the caption showing the same month."""
        d = self.cal.selectedDate()
        self.cal.setCurrentPage(d.year(), d.month())
        self.month.setText(d.toString(MONTH_FMT))

    def add_item(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.input.setFocus()
            return
        self.reload()
        self._events.setdefault(self._key(), []).append(text)
        cfgmod.save_events(self._events)
        self.input.clear()
        self.refresh()
        self._notify()

    def remove_selected(self) -> None:
        row = self.list.currentRow()
        self.reload()
        items = self._events.get(self._key(), [])
        if row < 0 or row >= len(items):
            return
        items.pop(row)
        if items:
            self._events[self._key()] = items
        else:
            self._events.pop(self._key(), None)
        cfgmod.save_events(self._events)
        self.refresh()
        self._notify()

    def _notify(self) -> None:
        self.changed.emit()
        if callable(self._on_cfg):
            self._on_cfg()

    # ------------------------------------------------------------------
    def apply_palette(self, pal: dict) -> None:
        self._pal = dict(pal)
