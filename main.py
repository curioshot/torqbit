#!/usr/bin/env python3
"""Top-screen always-on-top island with aora-bot face. Click to expand."""
import os
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QLockFile
from PySide6.QtCore import QStandardPaths

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    _HAS_WEBENGINE = True
except Exception:
    _HAS_WEBENGINE = False

from island.window import IslandWindow
from island import probe


def _single_instance_guard(app: QApplication):
    """Refuse a second copy: stale saves from duplicates clobber settings."""
    d = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not d:
        d = os.path.expanduser("~/.config/bot-island")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    lock = QLockFile(os.path.join(d, "bot-island.lock"))
    lock.setStaleLockTime(15000)
    if not lock.tryLock(100):
        print("bot-island is already running — refusing a second copy.")
        raise SystemExit(0)
    app._island_lock = lock  # keep alive for the process lifetime
    return lock


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--no-webengine" in argv:
        os.environ["BOT_ISLAND_NO_WEBENGINE"] = "1"
        argv = [a for a in argv if a != "--no-webengine"]
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(argv if argv else sys.argv[:1])
    app.setApplicationName("bot-island")
    app.setOrganizationName("bot-island")
    app.setQuitOnLastWindowClosed(True)
    # The probe worker owns a QThread; without this it is still running when
    # the interpreter tears down and Qt aborts.
    app.aboutToQuit.connect(probe.shutdown)
    _single_instance_guard(app)
    w = IslandWindow()
    w.show()
    w.raise_()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
