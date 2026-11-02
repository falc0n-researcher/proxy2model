"""
Record a browser you use yourself: every in-scope request any tab makes, with its response.

`proxy2model browse` opens Chrome with a fresh profile and attaches to it over the DevTools
Protocol. Every tab, popup, frame and worker is attached as it appears, paused until its network
is being recorded, so even the first request of a new tab is kept. Out-of-scope requests are never
recorded; nothing is blocked, so the app works as it would without proxy2model.

Recorded exchanges become Burp-style <item>s and go through the same parser and masking as an
export (see live.py); nothing raw is written.
"""

from __future__ import annotations

import base64
import threading
import time
from xml.etree.ElementTree import Element

from .browser import _Rec, CDP, WebSocket, rec_to_item

# targets whose traffic is the app's: tabs, popups, out-of-process frames, workers
_RECORDED = frozenset({"page", "iframe", "worker", "shared_worker", "service_worker"})
_NO_BODY = frozenset({"Image", "Font", "Media"})


class Recorder(threading.Thread):
    """Records one browser over its own DevTools connection until stopped or the browser goes away.

    `on_items` gets a list of <item>s about twice a second while anything new was recorded."""

    def __init__(self, ws_url: str, in_scope, on_items, max_body: int = 5 * 1024 * 1024):
        super().__init__(daemon=True)
        self.ws_url, self.in_scope, self.on_items, self.max_body = ws_url, in_scope, on_items, max_body
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.recs: dict[tuple[str, str], _Rec] = {}
        self.done: list[_Rec] = []
        self.recorded = 0
        self.error: str | None = None

    def run(self) -> None:
        try:
            self.cdp = CDP(WebSocket(self.ws_url))
            self.cdp.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True,
                                                   "flatten": True})
            self.ready.set()
            last = time.monotonic()
            while not self.stop.is_set():
                ev = self.cdp.next_event(0.2)
                if ev is not None:
                    self._handle(ev)
                if self.done and time.monotonic() - last > 0.5:
                    self._emit()
                    last = time.monotonic()
        except (ConnectionError, OSError):
            pass                                        # the browser was closed
        except Exception as e:                          # report, never take the session down with it
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.ready.set()
            self._emit()

    def _emit(self) -> None:
        items: list[Element] = []
        while self.done:
            item = rec_to_item(self.done.pop(0), self.in_scope)
            if item is not None:
                items.append(item)
        if items:
            self.recorded += len(items)
            self.on_items(items)

    def _call(self, method: str, params: dict | None, session: str, timeout: float = 10.0):
        try:
            return self.cdp.call(method, params, session, timeout)
        except (RuntimeError, TimeoutError):
            return {}

    def _handle(self, ev: dict) -> None:
        m, p, sid = ev["method"], ev.get("params", {}), ev.get("sessionId")
        if m == "Target.attachedToTarget":
            child, kind = p["sessionId"], p["targetInfo"].get("type")
            if kind in _RECORDED:
                self._call("Network.enable", {}, child)
                # a cached script or page would be recorded without its body, or not at all
                self._call("Network.setCacheDisabled", {"cacheDisabled": True}, child)
                if kind in ("page", "iframe"):           # its frames and workers, as they appear
                    self._call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True,
                                                        "flatten": True}, child)
            if p.get("waitingForDebugger"):
                self._call("Runtime.runIfWaitingForDebugger", {}, child)
            return
        if m == "Target.detachedFromTarget":
            gone = p.get("sessionId")
            for key in [k for k in self.recs if k[0] == gone]:
                del self.recs[key]
            return
        if not sid or not m.startswith("Network."):
            return
        key = (sid, p.get("requestId", ""))
        if m == "Network.requestWillBeSent":
            if p.get("redirectResponse") and key in self.recs:
                old = self.recs.pop(key)
                old.resp, old.redirect = p["redirectResponse"], True
                self.done.append(old)
            if not self.in_scope(p["request"].get("url", "")):
                return
            rec = _Rec(key[1])
            rec.req, rec.rtype = p["request"], p.get("type", "")
            rec.post = rec.req.get("postData")
            self.recs[key] = rec
        elif key not in self.recs:
            return
        elif m == "Network.requestWillBeSentExtraInfo":
            self.recs[key].extra_req = p.get("headers")
        elif m == "Network.responseReceived":
            self.recs[key].resp = p["response"]
        elif m == "Network.responseReceivedExtraInfo":
            self.recs[key].extra_resp = p.get("headers")
        elif m == "Network.loadingFinished":
            rec = self.recs.pop(key)
            if rec.resp:
                self._body(sid, rec)
                self.done.append(rec)
        elif m == "Network.loadingFailed":
            self.recs.pop(key, None)

    def _body(self, sid: str, rec: _Rec) -> None:
        if rec.rtype not in _NO_BODY:
            r = self._call("Network.getResponseBody", {"requestId": rec.id}, sid, 15)
            body = r.get("body", "")
            try:
                rec.body = (base64.b64decode(body) if r.get("base64Encoded") else body.encode("utf-8", "replace"))
            except ValueError:
                rec.body = b""
            rec.body = rec.body[: self.max_body]
        if rec.req.get("hasPostData") and rec.post is None:
            rec.post = self._call("Network.getRequestPostData", {"requestId": rec.id}, sid, 5).get("postData")
