"""
Live ingest: a local HTTP listener a proxy pushes traffic to as it happens.

`proxy2model serve` binds 127.0.0.1 and accepts `POST /ingest` with one exchange (or
`{"items": [...]}`) as JSON:

    {"request":  "<base64 raw HTTP request>",
     "response": "<base64 raw HTTP response>",      optional
     "host": "shop.example.com", "port": 443, "tls": true,
     "truncated": false}                             optional: the sender cut a body

host, port and tls are optional when the request line or its Host header says them.
Each exchange goes through the same parser and masking as an export: the raw bytes are
dropped as soon as it is parsed, and only the masked record is kept, appended to
`inputs/live.jsonl`. Every few seconds, if anything new arrived, the model and every
output (plus `openapi.json`) are rebuilt from all saved inputs.

The listener only answers JSON requests (a web page cannot send one without a CORS
preflight, which it never answers) and only for a loopback Host header (no DNS
rebinding). Binding another address needs a token.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import signal
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree.ElementTree import Element, SubElement

from .parse import Exchange, parse_elements

MAX_BODY = 32 << 20                 # one POST, before base64 decoding
LOOPBACK = ("127.0.0.1", "::1", "localhost")
INGEST_PATH = "/ingest"


def _b64(value) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def _host_header(raw: bytes) -> str:
    for line in raw.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
        k, _, v = line.partition(b":")
        if k.strip().lower() == b"host":
            return v.strip().decode("latin-1")
    return ""


def item_from_payload(p) -> Element | None:
    """One pushed exchange as the <item> element the parser reads, or None when it is not one."""
    if not isinstance(p, dict):
        return None
    raw_rq = _b64(p.get("request"))
    if not raw_rq:
        return None
    raw_rs = _b64(p.get("response")) or b""
    line = raw_rq.split(b"\r\n", 1)[0].split(b"\n", 1)[0].decode("latin-1")
    parts = line.split(" ")
    if len(parts) < 2:
        return None
    method, target = parts[0].upper(), parts[1]

    absolute = urllib.parse.urlsplit(target) if "://" in target else None
    tls = p.get("tls")
    if isinstance(tls, bool):
        scheme = "https" if tls else "http"
    elif absolute is not None and absolute.scheme in ("http", "https"):
        scheme = absolute.scheme
    else:
        scheme = "https"
    netloc = str(p.get("host") or "") or (absolute.netloc if absolute else "") or _host_header(raw_rq)
    hp = urllib.parse.urlsplit("//" + netloc.split("@")[-1])
    host = (hp.hostname or "").lower()
    if not host:
        return None
    try:
        port = int(p.get("port") or hp.port or (absolute.port if absolute else None) or 0)
    except (TypeError, ValueError):
        port = 0
    port = port or (443 if scheme == "https" else 80)
    path = ((absolute.path or "/") + ("?" + absolute.query if absolute.query else "")) if absolute else target

    item = Element("item")
    for tag, val in (("method", method), ("host", host), ("port", str(port)), ("protocol", scheme),
                     ("path", path or "/")):
        SubElement(item, tag).text = val
    SubElement(item, "request", {"base64": "true"}).text = base64.b64encode(raw_rq).decode()
    SubElement(item, "response", {"base64": "true"}).text = base64.b64encode(raw_rs).decode()
    if p.get("truncated") is True:              # the sender cut the body: say so in the model
        SubElement(item, "truncated")
    return item


class Live:
    """Masked exchanges waiting to be saved, and the file they are appended to."""

    def __init__(self, path: str, role: str | None = None):
        self.path = path
        self.role = role
        self.lock = threading.Lock()
        self.pending: list[Exchange] = []
        self.stats = {"items": 0, "parsed": 0, "skipped": 0}
        self.received = 0
        self.saved = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.saved = sum(1 for line in f if line.strip() and '"_stats"' not in line[:12])

    def ingest(self, payloads: list) -> tuple[int, int]:
        """Parse and mask each payload; returns (accepted, skipped)."""
        items = [item_from_payload(p) for p in payloads]
        stats: dict = {}
        parsed = list(parse_elements([i for i in items if i is not None], source="live",
                                     role=self.role, stats=stats))
        skipped = len(payloads) - len(parsed)
        with self.lock:
            for ex in parsed:
                ex.item = self.saved + len(self.pending)
                self.pending.append(ex)
            self.stats["items"] += len(payloads)
            self.stats["parsed"] += len(parsed)
            self.stats["skipped"] += skipped
            self.received += len(parsed)
        return len(parsed), skipped

    def flush(self) -> int:
        """Append what is pending to the input file in one write; returns how many were saved."""
        with self.lock:
            batch, stats = self.pending, self.stats
            self.pending, self.stats = [], {"items": 0, "parsed": 0, "skipped": 0}
        if not batch and not stats["items"]:
            return 0
        lines = [json.dumps(ex.to_record()) for ex in batch]
        lines.append(json.dumps({"_stats": stats, "_version": 1}))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.saved += len(batch)
        return len(batch)


def make_handler(live: Live, token: str | None, loopback_only: bool, verbose: bool = False,
                 on_error=lambda msg: None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "proxy2model"
        sys_version = ""
        # keep-alive: proxies reuse connections, and a send on one the server already closed
        # can be lost without an error on their side (seen with Caido's workflow sender)
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            if verbose:
                super().log_message(fmt, *args)

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            if code >= 400:
                self.close_connection = True        # an unread body must not leak into the next request
            self.send_response(code)
            if code >= 400:
                self.send_header("Connection", "close")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            if loopback_only:
                host = urllib.parse.urlsplit("//" + (self.headers.get("Host") or "")).hostname or ""
                if host.lower() not in LOOPBACK:
                    self._send(403, {"error": "Host must be a loopback name"})
                    return False
            if token:
                given = self.headers.get("X-Proxy2model-Token") or ""
                auth = self.headers.get("Authorization") or ""
                if auth.lower().startswith("bearer "):
                    given = given or auth[7:].strip()
                if not hmac.compare_digest(given.encode(), token.encode()):
                    self._send(401, {"error": "missing or wrong token"})
                    return False
            return True

        def do_GET(self):
            if not self._allowed():
                return
            if urllib.parse.urlsplit(self.path).path not in ("/", "/health"):
                return self._send(404, {"error": "not found"})
            with live.lock:
                pending = len(live.pending)
            self._send(200, {"tool": "proxy2model", "received": live.received,
                             "saved": live.saved, "pending": pending})

        def do_POST(self):
            if not self._allowed():
                return
            if urllib.parse.urlsplit(self.path).path != INGEST_PATH:
                return self._send(404, {"error": "not found"})
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                return self._send(415, {"error": "Content-Type must be application/json"})
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                return self._send(411, {"error": "Content-Length required"})
            if length < 0 or length > MAX_BODY:
                return self._send(413, {"error": f"body over {MAX_BODY} bytes"})
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return self._send(400, {"error": "body is not JSON"})
            if isinstance(body, dict) and "script_error" in body:        # the sender's script failed
                on_error(str(body["script_error"])[:2000])
                return self._send(202, {"accepted": 0, "skipped": 0})
            payloads = body.get("items") if isinstance(body, dict) and "items" in body else [body]
            if not isinstance(payloads, list):
                return self._send(400, {"error": "items must be a list"})
            accepted, skipped = live.ingest(payloads)
            self._send(202, {"accepted": accepted, "skipped": skipped})

    return Handler


class Rebuilder(threading.Thread):
    """Every `interval` seconds, saves what arrived and, if anything did, rebuilds.

    `report` gets one dict per rebuild: {"added", "saved", "summary", "seconds"}, or {"error"}."""

    def __init__(self, live: Live, rebuild, interval: float, report=print):
        super().__init__(daemon=True)
        self.live, self.rebuild, self.interval, self.report = live, rebuild, interval, report
        self.stop = threading.Event()
        self.last = 0.0                              # how long the last rebuild took

    def step(self) -> None:
        n = self.live.flush()
        if not n:
            return
        t0 = time.monotonic()
        try:
            summary = self.rebuild()
        except Exception as e:                      # a bad rebuild must not stop the listener
            self.report({"error": str(e)})
        else:
            self.report({"added": n, "saved": self.live.saved, "summary": summary,
                         "seconds": time.monotonic() - t0})
        self.last = time.monotonic() - t0

    def run(self) -> None:
        # a big session rebuilds slowly: wait at least twice as long as the last rebuild took,
        # so the listener never spends more than a third of its time rebuilding
        while not self.stop.wait(max(self.interval, 2 * self.last)):
            self.step()


def serve(live: Live, rebuild, bind: str = "127.0.0.1", port: int = 8765, token: str | None = None,
          interval: float = 5.0, verbose: bool = False, ready=None, report=print) -> None:
    """Run until interrupted; saves and rebuilds once more on the way out. `report` also gets
    {"script_error"} when a sender's script says it failed."""
    loopback = bind in ("127.0.0.1", "::1", "localhost")
    httpd = ThreadingHTTPServer((bind, port), make_handler(live, token, loopback, verbose,
                                                          on_error=lambda msg: report({"script_error": msg})))
    httpd.daemon_threads = True
    worker = Rebuilder(live, rebuild, interval, report)
    worker.start()

    def stop(_sig, _frame):
        raise KeyboardInterrupt

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, stop)             # `kill`, service managers: stop as cleanly as Ctrl-C
        signal.signal(signal.SIGINT, stop)              # also when started in the background
    if ready:
        ready(httpd)
    try:
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        worker.stop.set()
        worker.join(timeout=interval + 1)
        worker.step()
