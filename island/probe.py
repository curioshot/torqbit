"""Off-thread execution for the system-probe backend.

Every capability probe and every system read in sysctl.py is a
subprocess.run or a blocking file read. All of it used to be called from a
Qt timer on the GUI thread, which means the control centre could sit in a
single timer slot for the sum of every command's timeout — a measured worst
case of around nineteen seconds when nmcli, pactl, bluetoothctl and xrandr
all stalled. The UI simply froze.

This module gives that work its own thread. Callers use it synchronously
(`run(fn)`), which blocks only the worker and not the GUI:

    result = probes.run(lambda: sysctl.Backend.get().caps())

The contract is deliberately thin: one worker, a bounded queue, and a
shutdown that cannot hang. Nothing here touches Qt widgets, so no object
is moved across threads — only plain dicts and floats, which Qt delivers
through a queued signal.
"""
from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, QThread, Signal


class _Task:
    __slots__ = ("fn", "result", "error", "done", "thread")

    def __init__(self, fn):
        self.fn = fn
        self.result = None
        self.error: BaseException | None = None
        self.done = threading.Event()
        self.thread: threading.Thread | None = None


class _Worker(QThread):
    """Serial worker. One at a time, so probes cannot stampede the machine
    with concurrent nmcli/pactl spawns."""

    def __init__(self, queue_: "queue.Queue[_Task]", parent=None):
        super().__init__(parent)
        self._queue = queue_
        self._stop = False

    def run(self):  # noqa: D102
        while not self._stop:
            try:
                task = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if task is None:
                break
            try:
                task.result = task.fn()
            except BaseException as exc:       # noqa: BLE001
                task.error = exc
            finally:
                task.done.set()
        # Drain: anything still queued when we stop must not be left
        # blocking a caller that is waiting on it.
        while True:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                break
            if task is None:
                continue
            task.error = RuntimeError("prober shut down")
            task.done.set()

    def shutdown(self):
        """Stop the worker, waiting for any in-flight task first.

        A task already running is given a bounded chance to finish, because
        destroying a QThread mid-run aborts with "Destroyed while thread is
        still running". Only if that grace period expires do we terminate —
        at that point the alternative is an abort on interpreter exit.
        """
        self._stop = True
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        if not self.wait(5000):
            self.terminate()
            self.wait(1000)


class Prober(QObject):
    """The GUI-side handle. Create one; call run(); call shutdown()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: "queue.Queue[_Task]" = queue.Queue()
        self._worker = _Worker(self._queue, self)
        self._worker.start()
        self._shutdown = False

    def run(self, fn, timeout: float = 6.0, default=None):
        """Run `fn` on the worker thread and return its result.

        Returns `default` if the worker is gone, times out, or the callable
        raises — the caller is a UI paint path and cannot be allowed to
        propagate. `timeout` is a backstop only: individual probes already
        bound their own subprocess timeouts.
        """
        if self._shutdown:
            return default
        task = _Task(fn)
        try:
            self._queue.put_nowait(task)
        except Exception:
            return default
        if not task.done.wait(timeout):
            # The task is still running; we cannot cancel it safely, but the
            # caller must not be held. Drop the result on the floor.
            return default
        if task.error is not None:
            return default
        return task.result

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._worker.shutdown()


_default: Prober | None = None
_default_lock = threading.Lock()


def get() -> Prober:
    """The process-wide prober, created on first use.

    A QObject needs a QApplication to exist, but this is never touched
    before one does — the window builds it during construction.
    """
    global _default
    with _default_lock:
        if _default is None:
            _default = Prober()
        return _default


def run(fn, timeout: float = 6.0, default=None):
    """Convenience wrapper around the process-wide prober."""
    return get().run(fn, timeout=timeout, default=default)


def shutdown() -> None:
    global _default
    with _default_lock:
        if _default is not None:
            _default.shutdown()
            _default = None
