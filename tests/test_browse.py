"""`browse`: a browser the user drives is recorded tab by tab; active mode also crawls beside them."""

import json
import os
import threading
import time

import pytest

from proxy2model.cli import browse as browse_cli
from proxy2model.cli import main
from proxy2model.ingest.browser import CDP, WebSocket, find_chrome

from test_browser_crawl import App

import base64
import hashlib
from http.server import ThreadingHTTPServer


class WsApp(App):
    """The SPA, plus a WebSocket endpoint that completes its handshake."""

    def do_GET(self):
        if self.path != "/ws":
            return super().do_GET()
        self._rec()
        accept = base64.b64encode(hashlib.sha1((self.headers["Sec-WebSocket-Key"] +
                                                "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.wfile.write(bytes([0x81, 2]) + b"hi")          # one text frame, then the server closes
        self.close_connection = True


@pytest.fixture(scope="module")
def base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), WsApp)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()

pytestmark = pytest.mark.skipif(find_chrome() is None, reason="no Chrome/Chromium installed")


def session(base, tmp_path, monkeypatch, *flags, drive=None):
    """Run `browse` against the SPA; `drive(cdp)` plays the user, then the browser is closed."""
    box = {}
    real = browse_cli.launch_chrome

    def launch(*a, **kw):
        proc, url = real(*a, **kw)
        box["ws"] = url
        return proc, url
    monkeypatch.setattr(browse_cli, "launch_chrome", launch)
    App.log = []
    out = str(tmp_path)
    rc = {}
    t = threading.Thread(target=lambda: rc.setdefault("rc", main(
        ["browse", base + "/", "--yes", "--headless", "-w", "spa", "--scope", "127.0.0.1",
         "--interval", "0.5", "--out", out, *flags])), daemon=True)
    t.start()
    for _ in range(100):
        if "ws" in box:
            break
        time.sleep(0.1)
    user = CDP(WebSocket(box["ws"]))
    time.sleep(2)
    if drive:
        drive(user)
    user.call("Browser.close")
    t.join(60)
    assert not t.is_alive()
    with open(os.path.join(out, "spa", "model.json")) as f:
        model = json.load(f)
    return rc["rc"], model, os.path.join(out, "spa")


def test_passive_records_every_tab_the_user_opens(base, tmp_path, monkeypatch, capsys):
    def drive(cdp):
        for _ in range(50):                                          # the page and its script have loaded
            if any(e["p"] == "/api/items" for e in App.log):
                break
            time.sleep(0.1)
        page = [t for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page"][0]
        sid = cdp.call("Target.attachToTarget", {"targetId": page["targetId"], "flatten": True})["sessionId"]
        cdp.call("Runtime.evaluate", {"expression": "document.getElementById('more').click();"
                                      "new Image().src = '/logo.png';"
                                      "new WebSocket('ws://' + location.host + '/ws');"}, sid)
        cdp.call("Runtime.evaluate", {"expression": "window.open('/#/about')", "userGesture": True}, sid)   # a new tab
        time.sleep(3)

    rc, model, outdir = session(base, tmp_path, monkeypatch, "--passive", drive=drive)
    assert rc == 0
    with open(os.path.join(outdir, "inputs", "browse.jsonl")) as f:
        recorded = [json.loads(x) for x in f if '"_stats"' not in x[:12]]
    # /api/more: a click in the first tab; /api/about: a tab opened later, recorded from its first request
    assert {"/api/items", "/api/more", "/api/about"} <= {r["path"] for r in recorded}
    assert sum(r["path"] == "/" and r["method"] == "GET" for r in recorded) == 2
    assert "/logo.png" not in {r["path"] for r in recorded}          # images are not recorded
    assert any(r["path"] == "/ws" and r["status"] == 101 for r in recorded)   # the WebSocket handshake
    assert any(n["type"] == "endpoint" and n["label"].endswith("/ws") for n in model["nodes"])
    out = capsys.readouterr().out
    assert "visit next" in out and "/api/secret" in out.split("visit next", 1)[1]   # named in code, not reached
    assert {r["host"] for r in recorded} == {"127.0.0.1"}            # localhost is out of scope: not recorded
    assert any(n["type"] == "endpoint" for n in model["nodes"])
    assert ("GET", "/api/secret") not in {(e["m"], e["p"]) for e in App.log}   # passive sends nothing itself
    assert os.path.exists(os.path.join(outdir, "report.html"))


def test_active_crawls_beside_the_user(base, tmp_path, monkeypatch):
    def drive(cdp):
        for _ in range(60):
            if any(e["p"] == "/api/secret" for e in App.log):
                break
            time.sleep(0.5)

    rc, model, _ = session(base, tmp_path, monkeypatch, "--active", "--max-seconds", "40", drive=drive)
    assert rc == 0
    assert "/api/secret" in json.dumps(model)                         # reached by the crawl, not the user
    assert not any(e["p"].startswith(("/api/logout", "/api/delete")) for e in App.log)
    assert not any(e["m"] != "GET" for e in App.log)                 # it shares the login: GET only by default


def test_keep_login_keeps_the_profile_outside_the_output(base, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    rc, _, outdir = session(base, tmp_path, monkeypatch, "--passive", "--keep-login", "--role", "user")
    assert rc == 0
    profile = tmp_path / "config" / "proxy2model" / "profiles" / "spa-user"
    assert profile.is_dir() and any(profile.iterdir())
    assert not str(profile).startswith(outdir)


def test_needs_a_url_without_a_terminal(capsys):
    assert main(["browse", "--yes"]) == 2
    assert "URL" in capsys.readouterr().err
