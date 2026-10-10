"""Shared fixtures.

Every test that touches the filesystem is redirected into tmp_path: the
config module writes to ~/.config/bot-island and the image cache to
~/.cache/bot-island, and a test must never touch the real ones.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def cfg_home(tmp_path, monkeypatch):
    """Point config.py at a throwaway XDG root and rebind its paths."""
    from island import config as cfgmod

    root = tmp_path / "config"
    root.mkdir()
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", root)
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", root / "config.json")
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", root / "events.json")
    monkeypatch.setattr(cfgmod, "NOTES_FILE", root / "notes.txt")
    return cfgmod


@pytest.fixture
def qapp():
    """One QApplication for the whole session (Qt does not allow many)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    # The probe worker owns a QThread; leaving it running aborts at exit.
    from island import probe
    probe.shutdown()
