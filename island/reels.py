"""Native Instagram Reels bridge — replaces the ReelScroll Chrome extension.

The bot talks to a browser it can inject JavaScript into and drives the same
page-side engine the extension used (assets/reels/), with no extension, no
manifest and no browser permissions involved.

  chromium family   Chrome DevTools Protocol over WebSocket
  firefox          WebDriver BiDi over WebSocket (Remote Agent)

Both are wrapped in one small command/response client over QWebSocket, which
ships with PySide6 — this adds no dependency to the project.

Design notes
------------
* Injection is **probe and re-inject**, not preload/pre-inject. Every poll
  asks the page whether `window.__reelscroll` exists; if it does not (fresh
  navigation, new tab, browser restart) the payload is injected again. This
  is one code path for both transports and survives Instagram's SPA routing
  without relying on `addScriptToEvaluateOnNewDocument` / preload scripts.
* Settings live in the bot's config.json — a single source of truth. The page
  receives them by injection and, over CDP, can write back through the
  `__reelscrollHost` binding (the pill's speed / mini / position).
* Nothing here raises into the Qt event loop. Every transport failure
  degrades to "not connected", and the caller falls back to X11 keys.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import (QObject, QTimer, QUrl, Signal, Slot)
from PySide6.QtWebSockets import QWebSocket

from . import browsers
from . import config as cfgmod

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "reels"
PAYLOAD_FILES = ("host.js", "reels.js", "controller.js")

REELS_URL_RE = ("instagram.com/reel",)

# Settings the page understands. Mirrors config.DEFAULTS["instagram"] but is
# applied defensively: unknown keys are simply ignored by the JS.
PAGE_SETTINGS = (
    "enabled", "wheelEnabled", "invertWheel", "smooth", "cooldownMs",
    "wheelThreshold", "nextKey", "prevKey", "nextLabel", "prevLabel",
    "allowArrows", "controllerEnabled", "autoAdvance", "playbackRate",
    "controllerMini", "controllerPos",
)

POLL_MS = 1500
CONNECT_TIMEOUT_MS = 4000


class Transport:
    """Minimal JSON command/response client over a WebSocket."""

    transport = "?"

    def __init__(self, parent=None):
        self.ws = QWebSocket()
        self.ws.setParent(parent)
        self._mid = 0
        self._pending: dict[int, dict] = {}
        self._events: list[dict] = []
        self.ready = False
        self.last_error = ""
        self.ws.connected.connect(self._on_connected)
        self.ws.disconnected.connect(self._on_disconnected)
        self.ws.textMessageReceived.connect(self._on_text)
        self.ws.errorOccurred.connect(self._on_error)

    # -- subclass hooks -------------------------------------------------
    def on_connected(self) -> None:
        self.ready = True

    def on_disconnected(self) -> None:
        self.ready = False

    # -- plumbing -------------------------------------------------------
    def open(self, url: str) -> None:
        self.ws.open(QUrl(url))

    def close(self) -> None:
        self.ready = False
        try:
            self.ws.close()
        except Exception:
            pass

    def is_open(self) -> bool:
        return self.ws.isValid() and self.ready

    def send(self, method: str, params: dict | None = None,
             callback=None) -> None:
        """Fire a command. `callback(result, error)` runs on the Qt thread."""
        self._mid += 1
        mid = self._mid
        payload = {"id": mid, "method": method, "params": params or {}}
        self._pending[mid] = {"callback": callback, "method": method}
        try:
            self.ws.sendTextMessage(json.dumps(payload))
        except Exception as e:
            self._pending.pop(mid, None)
            if callback:
                callback(None, f"send failed: {e}")

    def drain_events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    # -- slots ----------------------------------------------------------
    def _on_connected(self):
        try:
            self.on_connected()
        except Exception as e:
            self.last_error = str(e)
            self.ready = False

    def _on_disconnected(self):
        for mid, p in list(self._pending.items()):
            cb = p["callback"]
            self._pending.pop(mid, None)
            if cb:
                cb(None, "disconnected")
        try:
            self.on_disconnected()
        except Exception:
            pass

    def _on_error(self, _code):
        self.last_error = self.ws.errorString()
        self.ready = False

    def _on_text(self, text: str):
        try:
            msg = json.loads(text)
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        if "id" in msg:
            mid = msg["id"]
            entry = self._pending.pop(mid, None)
            cb = entry["callback"] if entry else None
            err = None
            if self.transport == "bidi":
                if msg.get("type") == "error":
                    err = msg.get("error")
                else:
                    cb and cb(msg.get("result", {}), None)
                    return
            else:
                if msg.get("error"):
                    err = msg["error"]
                else:
                    cb and cb(msg.get("result", {}), None)
                    return
            if cb:
                cb(None, err or "error")
        elif "method" in msg:
            self._events.append(msg)

    @staticmethod
    def _call(cb, result, error):
        if cb:
            cb(result, error)


class CdpTransport(Transport):
    transport = "cdp"

    def on_connected(self):
        self.send("Runtime.enable")
        self.send("Page.enable")
        self.send("Runtime.addBinding", {"name": "__reelscrollHost"})
        self.ready = True


class BidiTransport(Transport):
    """Firefox Remote Agent (WebDriver BiDi).

    Firefox 129+ dropped CDP, so the Remote Agent speaks BiDi only and there
    is no /json/version — connect straight to /session.
    """

    transport = "bidi"
    session_id = ""
    context = ""
    contexts: list[dict] = []

    def on_connected(self):
        def got_session(result, error):
            # Firefox allows a single explicit session. When one already exists
            # (a second island, a previous run that did not disconnect cleanly)
            # session.new fails — but every command still resolves against the
            # Remote Agent's implicit session, so carry on rather than give up.
            if error:
                self.last_error = f"session.new: {error}"
            else:
                self.session_id = (result or {}).get("sessionId", "")
            self.send("session.subscribe", {"events": [
                "browsingContext.contextCreated",
                "browsingContext.contextDestroyed",
                "browsingContext.navigationStarted"]})
            # Tabs that already existed before we connected never fire
            # contextCreated, so resolve the tree explicitly.
            self.send("browsingContext.getTree", {}, self._got_tree)

        self.send("session.new", {"capabilities": {}}, got_session)

    def _got_tree(self, result, error):
        if error or not result:
            self.last_error = f"getTree failed: {error}"
            return
        self.contexts = _flatten_contexts(result.get("contexts", []))
        self.context = self._pick().get("context", "")
        self.ready = True

    def _pick(self) -> dict:
        for needle in REELS_URL_RE:
            for c in self.contexts:
                if needle in (c.get("url") or "").lower():
                    return c
        return self.contexts[0] if self.contexts else {}


class ReelsBridge(QObject):
    """Owns the browser connection and the page-side Reels API."""

    connected = Signal(bool)
    statusChanged = Signal(dict)
    settingsRequested = Signal(dict)   # page -> bot persistence request

    def __init__(self, parent=None):
        super().__init__(parent)
        self.family: str | None = None
        self.transport = None
        self.target_url = ""
        self._state = self._blank_state()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self.tick)
        self._config: dict = {}
        self._injecting = False
        self.port: int | None = None

    # ------------------------------------------------------------------ state
    @staticmethod
    def _blank_state() -> dict:
        return {"connected": False, "active": False, "reelsPage": False,
                "count": 0, "index": 0, "url": "", "detail": "idle",
                "browser": "", "family": ""}

    def state(self) -> dict:
        return dict(self._state)

    # ------------------------------------------------------------------ config
    def configure(self, cfg: dict) -> None:
        """Receive the `instagram` config block."""
        self._config = dict(cfg or {})
        if self.transport and self.transport.is_open():
            self._push_settings()

    def _page_config(self) -> dict:
        out = {k: self._config[k] for k in PAGE_SETTINGS if k in self._config}
        # The bot's key bindings are stored as X keysyms for XTest; the page
        # wants DOM `code` values. Map the common ASCII case.
        return out

    # ------------------------------------------------------------------ lifecycle
    def start(self, family: str, port: int) -> None:
        self.stop()
        from . import browsers
        self.port = port
        if not family or not port:
            self._set({"connected": False, "detail": "no browser",
                       "family": family or ""})
            return
        self.family = family
        transport_name = browsers.FAMILIES.get(family, ((), "cdp"))[1]
        self.transport = (CdpTransport(self) if transport_name == "cdp"
                          else BidiTransport(self))
        self._set({"browser": browsers.FAMILIES[family][0][0],
                   "family": family, "detail": "connecting"})
        if transport_name == "cdp":
            url = self._cdp_url(port)
        else:
            url = f"ws://127.0.0.1:{port}/session"
        if not url:
            self._set({"connected": False, "detail": "no debug port"})
            self.transport = None
            return
        self.transport.open(url)

    def stop(self) -> None:
        self._poll.stop()
        self.port = None
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        self._set({"connected": False, "detail": "stopped"})

    def begin_polling(self) -> None:
        self._poll.start(POLL_MS)

    # ------------------------------------------------------------------ targets
    def _cdp_url(self, port: int) -> str | None:
        """WebSocket URL of the first Instagram tab, else any page."""
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/list", timeout=1.5) as r:
                targets = json.loads(r.read().decode())
        except Exception:
            return None
        pages = [t for t in targets if t.get("type") == "page"]
        for want in ("reel", "instagram"):
            for t in pages:
                if want in (t.get("url") or "").lower():
                    self.target_url = t.get("url", "")
                    return t.get("webSocketDebuggerUrl")
        return pages[0].get("webSocketDebuggerUrl") if pages else None

    # ------------------------------------------------------------------ eval
    def _evaluate(self, expression: str, callback=None) -> None:
        """Run JS and hand back the JSON-decoded result of the last expression."""
        if callback is None:
            callback = lambda _r, _e: None
        if self.transport is None or not self.transport.is_open():
            callback(None, "not connected")
            return
        wrapped = (f"JSON.stringify((function(){{ try {{ return ({expression}); }}"
                   f" catch(e) {{ return {{\"__err\": String(e)}}; }} }})())")
        if self.transport.transport == "cdp":
            self.transport.send("Runtime.evaluate", {
                "expression": wrapped, "returnByValue": True,
                "awaitPromise": True,
            }, _unwrap(callback))
        else:
            ctx = getattr(self.transport, "context", "")
            if not ctx:
                # A tab may have opened since the last tree lookup.
                self.transport.send("browsingContext.getTree", {},
                                    self.transport._got_tree)
                callback(None, "no browsing context")
                return

            def done(result, error):
                if error or result is None:
                    callback(None, error)
                    return
                val = result.get("result", {}).get("value")
                callback(_maybe_json(val), None)
            self.transport.send("script.evaluate", {
                "expression": wrapped, "target": {"context": ctx},
                "awaitPromise": True,
            }, done)

    # ------------------------------------------------------------------ injection
    def _payload(self) -> str:
        parts = [
            f"(function(){{ try {{ window.__reelscrollConfig = "
            f"{json.dumps(self._page_config())}; }} catch(e) {{}} }})();"
        ]
        for name in PAYLOAD_FILES:
            src = (ASSETS / name).read_text(encoding="utf-8")
            parts.append(f"(function(){{ {src} }})();")
        css = (ASSETS / "reels.css").read_text(encoding="utf-8")
        parts.append(
            "(function(){ try {"
            " if (!document.getElementById('reelscroll-css')) {"
            "   var s=document.createElement('style');"
            "   s.id='reelscroll-css';"
            f"   s.textContent={json.dumps(css)};"
            "   (document.head||document.documentElement).appendChild(s); }"
            " } catch(e){} })();"
        )
        return "\n;\n".join(parts)

    def inject(self, callback=None) -> None:
        if self._injecting:
            if callback:
                callback(False, "busy")
            return
        self._injecting = True

        def done(result, error):
            self._injecting = False
            ok = not error and result is not None
            if callback:
                callback(ok, error)

        if self.transport is not None and self.transport.transport == "cdp":
            self._evaluate("1", lambda _r, e: self._do_inject(done))
        else:
            self._do_inject(done)

    def _do_inject(self, done):
        if self.transport is None:
            done(None, "no transport")
            return
        src = self._payload()
        if self.transport.transport == "cdp":
            self.transport.send("Runtime.evaluate", {
                "expression": src, "returnByValue": True, "awaitPromise": True,
            }, lambda r, e: done(r, e))
        else:
            ctx = getattr(self.transport, "context", "")
            if not ctx:
                done(None, "no browsing context")
                return
            self.transport.send("script.evaluate", {
                "expression": src, "target": {"context": ctx},
                "awaitPromise": False,
            }, lambda r, e: done(r, e))

    # ------------------------------------------------------------------ commands
    def next_reel(self, callback=None) -> None:
        self._command("window.__reelscroll ? window.__reelscroll.next('bot') : null",
                      callback)

    def prev_reel(self, callback=None) -> None:
        self._command("window.__reelscroll ? window.__reelscroll.prev('bot') : null",
                      callback)

    def _command(self, expr: str, callback=None) -> None:
        self._evaluate(expr, lambda r, e: (callback or (lambda *_: None))(r, e))

    def refresh(self) -> None:
        if self.transport and self.transport.is_open():
            self._push_settings()

    def _push_settings(self) -> None:
        cfg = self._page_config()
        expr = ("window.__reelscroll ? window.__reelscroll.setSettings("
                f"{json.dumps(cfg)}) : null")
        self._evaluate(expr)

    # ------------------------------------------------------------------ tick
    @Slot()
    def tick(self) -> None:
        if self.transport is None:
            return
        if not self.transport.is_open():
            self._set({"connected": False,
                       "detail": self.transport.last_error or "connecting"})
            return
        self._handle_events()
        # Probe-and-reinject: one round trip tells us both liveness and
        # whether the payload survived the last navigation.
        self._evaluate("window.__reelscroll ? 1 : 0", self._after_probe)

    def _after_probe(self, result, error):
        if error:
            self._set({"connected": False, "detail": error})
            return
        if not result:
            self.inject(lambda ok, e: self._set(
                {"connected": ok, "detail": "injected" if ok else (e or "inject failed")}))
            return
        self._set({"connected": True, "detail": "connected"})
        self._evaluate(
            "window.__reelscroll ? window.__reelscroll.status() : null",
            self._after_status)

    def _after_status(self, result, error):
        if error or not isinstance(result, dict):
            return
        self._set({
            "active": bool(result.get("active")),
            "reelsPage": bool(result.get("reelsPage")),
            "count": int(result.get("count") or 0),
            "index": int(result.get("index") or 0),
            "url": result.get("url", ""),
        })

    def _handle_events(self) -> None:
        if self.transport is None:
            return
        for ev in self.transport.drain_events():
            method = ev.get("method")
            params = ev.get("params") or {}
            if self.transport.transport == "cdp":
                if method == "Runtime.bindingCalled" and \
                        params.get("name") == "__reelscrollHost":
                    self._on_page_write(params.get("payload") or "")
            else:
                if method == "browsingContext.contextCreated":
                    ctx = params.get("context") or {}
                    if _is_top(ctx):
                        self.transport.contexts.append(ctx)
                        self.transport.context = self.transport._pick().get(
                            "context", "")
                        # A fresh tab: re-resolve and re-inject.
                        self.inject(lambda ok, e: None)
                elif method == "browsingContext.contextDestroyed":
                    dead = params.get("context")
                    self.transport.contexts = [
                        c for c in self.transport.contexts
                        if c.get("context") != dead]
                    if dead == self.transport.context:
                        self.transport.context = self.transport._pick().get(
                            "context", "")
                elif method == "browsingContext.navigationStarted":
                    # Same context id, fresh document: the payload is gone.
                    self.transport.context = ""
                    self.transport.send(
                        "browsingContext.getTree", {},
                        self.transport._got_tree)

    def _on_page_write(self, payload: str) -> None:
        """The pill changed a setting — persist it through the normal config path."""
        try:
            patch = json.loads(payload)
        except Exception:
            return
        if isinstance(patch, dict) and patch:
            self.settingsRequested.emit(patch)

    # ------------------------------------------------------------------ helpers
    def _set(self, patch: dict) -> None:
        changed = False
        for k, v in patch.items():
            if self._state.get(k) != v:
                self._state[k] = v
                changed = True
        if changed:
            self.statusChanged.emit(dict(self._state))
            self.connected.emit(bool(self._state.get("connected")))


class ReelsService(QObject):
    """Ties the bridge, the browser launcher and the X11 fallback together.

    This is what the Service tab talks to. It never raises: every failure
    path ends in a status string the UI can show.

    Control order for a next/prev request:
      1. the injected page (full control: 1:1 wheel, pill, PiP, auto-advance)
      2. X11 + XTest key synthesis on the Instagram window (any browser,
         keys only) — the pre-existing fallback, kept intact
    """

    statusChanged = Signal(dict)
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = ReelsBridge(self)
        self.bridge.statusChanged.connect(self._on_status)
        self.bridge.settingsRequested.connect(self._on_page_settings)
        self.family = "chromium"
        self._config: dict = {}
        self._busy_until = 0.0
        self._launched_by_us: set[str] = set()

    # ------------------------------------------------------------------ config
    def sync_config(self, cfg: dict) -> None:
        self._config = dict(cfg or {})
        self.bridge.configure(self._config)

    def _on_page_settings(self, patch: dict) -> None:
        """The pill changed a setting: persist through the normal config path."""
        try:
            from . import config as cfg
            full = cfg.load()
            full.setdefault("instagram", {}).update(patch)
            cfg.save(full)
            self._config = full["instagram"]
        except Exception as e:
            self.message.emit(f"could not save page setting: {e}")

    # ------------------------------------------------------------------ status
    def _on_status(self, state: dict) -> None:
        self.statusChanged.emit(self.state())

    def state(self) -> dict:
        s = dict(self.bridge.state())
        s["enabled"] = bool(self._config.get("service"))
        s["family"] = s.get("family") or self.family
        s["browsers"] = browsers.discover()
        s["shims"] = browsers.shim_status()
        if not s.get("enabled"):
            s["detail"] = "service off"
        elif s.get("connected") and s.get("reelsPage"):
            s["detail"] = f"Controlling Reels — {s.get('count', 0)} found"
        elif s.get("connected"):
            s["detail"] = "Connected — not on a Reels page"
        return s

    # ------------------------------------------------------------------ browser
    def set_family(self, family: str) -> None:
        if family and family != self.family:
            self.family = family
            self.bridge.stop()

    def open_instagram(self) -> str:
        """Start the instrumented browser. Returns a human-readable status."""
        from . import config as cfg
        url = self._config.get("url") or browsers.REELS_URL
        app_mode = bool(self._config.get("appMode", True))
        res = browsers.launch(self.family, url=url, app_mode=app_mode)
        if not res.get("ok"):
            return res.get("error", "could not start browser")
        self._launched_by_us.add(self.family)
        if res.get("already"):
            return f"{self.family} already running — attaching"
        return f"Opening Instagram in {self.family}… (first run: log in once)"

    def install_shim(self) -> str:
        res = browsers.install_shim(self.family)
        if not res.get("ok"):
            return res.get("error", "shim install failed")
        return f"Installed {res['path']} — every {self.family} launch is now instrumented"

    def uninstall_shim(self) -> str:
        res = browsers.uninstall_shim(self.family)
        if not res.get("ok"):
            return res.get("error", "shim remove failed")
        return f"Removed the wrapper for {self.family}"

    # ------------------------------------------------------------------ poll
    def tick(self) -> None:
        """Called from the Service tab's timer: keep the connection honest."""
        on = bool(self._config.get("service"))
        if not on:
            self.bridge.stop()
            return
        port = browsers.current_port(self.family)
        if port is None:
            self.bridge.stop()
            self.statusChanged.emit(self.state())
            return
        # Only (re)connect when the browser's debug port actually changed.
        # Comparing against the bridge — not a local transport reference —
        # keeps this stable; otherwise every tick would drop the live socket.
        if self.bridge.port != port:
            self.bridge.start(self.family, port)
            self.bridge.begin_polling()

    # ------------------------------------------------------------------ control
    def next_reel(self, callback=None) -> None:
        self._turn(True, callback)

    def prev_reel(self, callback=None) -> None:
        self._turn(False, callback)

    def _turn(self, forward: bool, callback=None) -> None:
        cb = callback or (lambda r, e: None)
        st = self.bridge.state()
        if st.get("connected") and st.get("active"):
            fn = self.bridge.next_reel if forward else self.bridge.prev_reel
            fn(lambda r, e: cb(("native", r), e))
            return
        # Fallback: synthesise the key into the focused Instagram window.
        from . import services as svc
        sym = int(self._config.get("next_keysym" if forward else "prev_keysym",
                                   83 if forward else 87))
        ok, msg = svc.send_reel_key(sym)
        cb(("x11", {"ok": ok, "detail": msg}), None)


def _is_top(ctx: dict) -> bool:
    """Top-level browsing context?

    Firefox 140 omits `contextType` entirely; only an explicit "tab" (a child
    of a window) should be excluded.
    """
    return (ctx or {}).get("contextType") not in ("tab",)


def _flatten_contexts(contexts) -> list[dict]:
    """Every context in the tree, windows and tabs alike, parents first."""
    out = []
    for c in contexts or []:
        if _is_top(c):
            out.append(c)
        out.extend(_flatten_contexts(c.get("children")))
    return out


def _unwrap(callback):
    """Adapt a CDP Runtime.evaluate result to (json_value, error)."""
    def inner(result, error):
        if error or result is None:
            callback(None, error)
            return
        if result.get("exceptionDetails"):
            callback(None, str(result["exceptionDetails"])[:200])
            return
        val = result.get("result", {}).get("value")
        callback(_maybe_json(val), None)
    return inner


def _maybe_json(val):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val
