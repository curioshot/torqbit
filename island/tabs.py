"""Expanded-panel tabs: clock/bot, calendar, system+notes."""
from __future__ import annotations

from datetime import datetime, timezone

import psutil
from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    QCalendarWidget, QListWidget, QLineEdit, QTextEdit, QProgressBar,
    QComboBox,
)

from . import config as cfgmod
from . import icons as iconsmod
from . import sensors as sensorsmod
from . import themes as themesmod


class BotTab(QWidget):
    """Time + emotion controls. Face widget lives in panel header; this tab drives it."""

    EMOTIONS = [
        ("02", "Idle"), ("10", "Happy"), ("30", "Thinking"),
        ("32", "Busy"), ("35", "Listening"), ("33", "Done"),
        ("00", "Sleep"), ("21", "Angry"),
    ]
    EMOTION_ICONS = {"33": "party"}

    def __init__(self, on_emotion, on_shape, on_face=None, on_seed=None, parent=None):
        super().__init__(parent)
        self._on_emotion = on_emotion
        self._on_shape = on_shape
        self._on_face = on_face or (lambda _e: None)
        self._on_seed = on_seed or (lambda _s: None)
        # styling is owned by island.themes (applied to the tab widget)
        lay = QVBoxLayout(self)

        self.clock = QLabel("--:--")
        self.clock.setAlignment(Qt.AlignCenter)
        self.clock.setStyleSheet("font-size: 40px; font-weight: 700;")
        self.date = QLabel("")
        self.date.setAlignment(Qt.AlignCenter)
        self.date.setStyleSheet("color:#a9a6a0; font-size: 13px;")
        lay.addWidget(self.clock)
        lay.addWidget(self.date)

        utc = QHBoxLayout()
        self.utc_lbl = QLabel("")
        self.utc_lbl.setAlignment(Qt.AlignCenter)
        self.utc_lbl.setStyleSheet("color:#7d7a75; font-size: 11px;")
        utc.addWidget(self.utc_lbl)
        lay.addLayout(utc)

        grid = QGridLayout()
        self.emo_buttons: dict[str, QPushButton] = {}
        for i, (eid, name) in enumerate(self.EMOTIONS):
            b = QPushButton(name)
            b.setToolTip(f"emotionId {eid}")
            if eid in self.EMOTION_ICONS:
                b.setIcon(iconsmod.icon(self.EMOTION_ICONS[eid], 14))
            b.clicked.connect(lambda _=False, e=eid: self._on_emotion(e))
            grid.addWidget(b, i // 4, i % 4)
            self.emo_buttons[eid] = b
        lay.addLayout(grid)

        row = QHBoxLayout()
        row.addWidget(QLabel("Shape:"))
        self.shape = QComboBox()
        self.shape.addItems(["blob", "wedge", "gem"])
        self.shape.currentTextChanged.connect(self._on_shape)
        row.addWidget(self.shape)
        row.addStretch(1)
        lay.addLayout(row)

        face_row = QHBoxLayout()
        face_row.addWidget(QLabel("Face:"))
        self.face = QComboBox()
        self.face.addItems(["blobatar", "aora", "simple"])
        self.face.setToolTip("blobatar = geometric creature (pick any name)\n"
                             "aora = EmotionBall (32 moods)\nsimple = built-in eyes")
        self.face.currentTextChanged.connect(self._on_face)
        face_row.addWidget(self.face)
        lay.addLayout(face_row)

        seed_row = QHBoxLayout()
        self.seed = QLineEdit()
        self.seed.setPlaceholderText("creature name — any string (blobatar)")
        self.seed.returnPressed.connect(lambda: self._on_seed(self.seed.text()))
        seed_row.addWidget(self.seed, 1)
        self.shuffle_btn = QPushButton()
        self.shuffle_btn.setIcon(iconsmod.icon("dice", 18))
        self.shuffle_btn.setFixedWidth(36)
        self.shuffle_btn.setToolTip("Surprise me: random creature")
        self.shuffle_btn.clicked.connect(
            lambda: self._on_seed(iconsmod.SHUFFLE_SENTINEL))
        seed_row.addWidget(self.shuffle_btn)
        lay.addLayout(seed_row)
        lay.addStretch(1)

        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(1000)
        self._tick()

    def _tick(self):
        now = datetime.now()
        self.clock.setText(now.strftime("%H:%M"))
        self.date.setText(now.strftime("%A  %Y-%m-%d"))
        self.utc_lbl.setText("UTC " + datetime.now(timezone.utc).strftime("%H:%M"))

    def set_shape(self, s: str):
        self.shape.blockSignals(True)
        idx = self.shape.findText(s)
        if idx >= 0:
            self.shape.setCurrentIndex(idx)
        self.shape.blockSignals(False)

    def set_face(self, f: str):
        self.face.blockSignals(True)
        idx = self.face.findText(f)
        if idx >= 0:
            self.face.setCurrentIndex(idx)
        self.face.blockSignals(False)

    def set_seed(self, s: str):
        if self.seed.text() != s:
            self.seed.blockSignals(True)
            self.seed.setText(s)
            self.seed.blockSignals(False)


class CalendarTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        lay.addWidget(self.cal)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Add event for selected date… (Enter)")
        self.add_btn = QPushButton("Add")
        row.addWidget(self.input, 1)
        row.addWidget(self.add_btn)
        lay.addLayout(row)
        self.events = cfgmod.load_events()
        self.cal.selectionChanged.connect(self.refresh)
        self.add_btn.clicked.connect(self.add_event)
        self.input.returnPressed.connect(self.add_event)
        self.refresh()

    def _key(self) -> str:
        d: QDate = self.cal.selectedDate()
        return d.toString("dd-mm-yyyy")

    def refresh(self):
        self.list.clear()
        for e in self.events.get(self._key(), []):
            self.list.addItem(e)
        if self.list.count() == 0:
            self.list.addItem("(no events — type above to add)")

    def add_event(self):
        txt = self.input.text().strip()
        if not txt:
            return
        self.events.setdefault(self._key(), []).append(txt)
        cfgmod.save_events(self.events)
        self.input.clear()
        self.refresh()


class SystemNotesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("System"))
        self.cpu_bar = QProgressBar()
        self.mem_bar = QProgressBar()
        self.cpu_lbl = QLabel("CPU --%")
        self.mem_lbl = QLabel("MEM --%")
        temp_row = QHBoxLayout()
        self.temp_icon = QLabel()
        pm = iconsmod.pixmap("thermo", 14)
        if pm is not None:
            self.temp_icon.setPixmap(pm)
        else:
            self.temp_icon.setText("T")
        self.temp_lbl = QLabel("Temp —")
        temp_row.addWidget(self.temp_icon)
        temp_row.addWidget(self.temp_lbl, 1)
        for w in (self.cpu_lbl, self.cpu_bar, self.mem_lbl, self.mem_bar):
            lay.addWidget(w)
        lay.addLayout(temp_row)
        lay.addWidget(QLabel("Notes (autosaved)"))
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Scratchpad…")
        self.notes.setText(cfgmod.load_notes())
        lay.addWidget(self.notes, 1)

        self._t = QTimer(self)
        self._t.timeout.connect(self._sys_tick)
        self._t.start(1500)
        self._sys_tick()

        self._save_t = QTimer(self)
        self._save_t.setSingleShot(True)
        self.notes.textChanged.connect(lambda: self._save_t.start(800))
        self._save_t.timeout.connect(lambda: cfgmod.save_notes(self.notes.toPlainText()))

    def _sys_tick(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
        except Exception:
            cpu, mem = 0, 0
        self.cpu_bar.setValue(int(cpu))
        self.mem_bar.setValue(int(mem))
        self.cpu_lbl.setText(f"CPU {cpu:.0f}%")
        self.mem_lbl.setText(f"MEM {mem:.0f}%")
        self.temp_lbl.setText(f"Temp {sensorsmod.format_temp(sensorsmod.get_cpu_temp())}")


class AppearanceTab(QWidget):
    """Theme picker + creature backdrop. Styled by island.themes."""

    def __init__(self, on_theme=None, on_bg=None, parent=None):
        super().__init__(parent)
        self._on_theme = on_theme or (lambda _t: None)
        self._on_bg = on_bg or (lambda _b: None)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Theme"))
        theme_row = QHBoxLayout()
        self.theme = QComboBox()
        self._theme_keys: list[str] = []
        for key, label, desc in themesmod.available():
            self.theme.addItem(label)
            self._theme_keys.append(key)
        self.theme.currentIndexChanged.connect(self._theme_chosen)
        theme_row.addWidget(self.theme, 1)
        lay.addLayout(theme_row)
        self.theme_desc = QLabel("")
        self.theme_desc.setWordWrap(True)
        lay.addWidget(self.theme_desc)
        lay.addSpacing(6)
        bg_row = QHBoxLayout()
        bg_row.addWidget(QLabel("Backdrop:"))
        self.bg = QComboBox()
        self.bg.addItems(["none", "squircle", "circle", "square"])
        self.bg.setToolTip("Creature plate behind the blobatar face")
        self.bg.currentTextChanged.connect(self._on_bg)
        bg_row.addWidget(self.bg, 1)
        lay.addLayout(bg_row)
        lay.addStretch(1)

    def _theme_chosen(self, idx: int):
        if 0 <= idx < len(self._theme_keys):
            key = self._theme_keys[idx]
            for k, _label, desc in themesmod.available():
                if k == key:
                    self.theme_desc.setText(desc)
                    break
            self._on_theme(key)

    def set_theme(self, key: str):
        if key in self._theme_keys:
            self.theme.blockSignals(True)
            self.theme.setCurrentIndex(self._theme_keys.index(key))
            for k, _label, desc in themesmod.available():
                if k == key:
                    self.theme_desc.setText(desc)
                    break
            self.theme.blockSignals(False)

    def set_bg(self, bg: str):
        self.bg.blockSignals(True)
        idx = self.bg.findText(bg)
        if idx >= 0:
            self.bg.setCurrentIndex(idx)
        self.bg.blockSignals(False)
