"""`serve`: live traffic pushed over HTTP builds the same masked model as an export."""

import base64
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from proxy2model.ingest import serve as live_serve
from proxy2model.cli import main
from proxy2model.cli.live import caido_script
from proxy2model.ingest.serve import Live, item_from_payload

SECRET = "SUPERSECRETCOOKIE123"


def b(s):
    return base64.b64encode(s.encode()).decode()


def pair(method, path, status=200, body="", host="shop.test"):
    rq = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nCookie: sid={SECRET}\r\n"
    if body:
        rq += "Content-Type: application/json\r\n"
    rq += "\r\n" + body
    rs = f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\n\r\n{{}}"
    return {"request": b(rq), "response": b(rs), "tls": True}


def test_payload_to_item():
    item = item_from_payload(pair("GET", "/api/users/7?x=1"))
    assert item.find("host").text == "shop.test"
    assert item.find("port").text == "443"
    assert item.find("protocol").text == "https"
    assert item.find("path").text == "/api/users/7?x=1"
    # proxy-form request line, request-only sender (`target` + `raw_data`)
    item = item_from_payload({"target": "api.test:8080", "raw_data": b("GET http://api.test:8080/v1/a HTTP/1.1\r\n\r\n")})
    assert (item.find("host").text, item.find("port").text, item.find("protocol").text,
            item.find("path").text) == ("api.test", "8080", "http", "/v1/a")
    for junk in ({}, {"request": "not base64!"}, {"request": b("nonsense")}, [], "x"):
        assert item_from_payload(junk) is None


def test_live_appends_masked_records(tmp_path):
    live = Live(str(tmp_path / "inputs" / "live.jsonl"))
    assert live.ingest([pair("GET", "/api/a"), {"junk": 1}]) == (1, 1)
    assert live.flush() == 1
    assert live.flush() == 0
    text = (tmp_path / "inputs" / "live.jsonl").read_text()
    assert SECRET not in text
    # a restart counts what an earlier session saved
    assert Live(str(tmp_path / "inputs" / "live.jsonl")).saved == 1


@pytest.fixture
def server(tmp_path):
    """`proxy2model serve` on a free port, in a thread; yields (port, outdir, stop)."""
    out = tmp_path / "out"
    started = threading.Event()
    box = {}
    real = live_serve.serve

    def capture(*a, **kw):
        user_ready = kw.get("ready")

        def ready(httpd):
            box["httpd"] = httpd
            if user_ready:
                user_ready(httpd)
            started.set()
        kw["ready"] = ready
        return real(*a, **kw)

    live_serve.serve = capture
    rc = {}
    t = threading.Thread(target=lambda: rc.setdefault("rc", main(
        ["serve", "-w", "shop", "--out", str(out), "--port", "0", "--interval", "0.2"])), daemon=True)
    t.start()
    assert started.wait(10)
    port = box["httpd"].server_address[1]

    def stop():
        box["httpd"].shutdown()
        t.join(10)
        return rc.get("rc")

    try:
        yield port, out / "shop", stop
    finally:
        live_serve.serve = real
        if t.is_alive():
            stop()


def post(port, obj, ct="application/json", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/ingest", data=json.dumps(obj).encode(),
                                 headers={"Content-Type": ct, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_serve_end_to_end(server):
    port, outdir, stop = server
    assert post(port, {"items": [pair("GET", f"/api/users/{i}") for i in range(3)]}) == \
        (202, {"accepted": 3, "skipped": 0})
    assert post(port, pair("POST", "/api/orders", 201, '{"qty": 2}'))[0] == 202
    # a page cannot send JSON without a preflight; a rebinding page has a foreign Host
    assert post(port, pair("GET", "/x"), ct="text/plain")[0] == 415
    assert post(port, pair("GET", "/x"), headers={"Host": "evil.example"})[0] == 403
    assert stop() == 0

    model = json.loads((outdir / "model.json").read_text())
    labels = {n["label"] for n in model["nodes"] if n["type"] == "endpoint"}
    assert {"GET /api/users/{id}", "POST /api/orders"} <= labels
    spec = json.loads((outdir / "openapi.json").read_text())
    assert "/api/users/{id}" in spec["paths"]
    for root, _, files in os.walk(outdir):
        for fn in files:
            with open(os.path.join(root, fn), "rb") as f:
                assert SECRET.encode() not in f.read(), fn


def test_one_session_is_one_build(server, capsys):
    port, outdir, stop = server
    post(port, pair("GET", "/api/a"))
    for _ in range(50):                         # wait for the first rebuild
        if (outdir / "model.json").exists():
            break
        threading.Event().wait(0.1)
    post(port, pair("GET", "/api/b"))
    assert stop() == 0
    capsys.readouterr()
    assert main(["builds", "shop", "--out", str(outdir.parent)]) == 0
    out = capsys.readouterr().out
    assert "1 build(s)" in out and "live" in out


def test_token_and_bind(tmp_path, capsys):
    assert main(["serve", "--bind", "0.0.0.0", "--out", str(tmp_path)]) == 2
    assert "--token" in capsys.readouterr().err
    js = caido_script("http://127.0.0.1:9999/ingest", "t0k")
    assert 'const INGEST = "http://127.0.0.1:9999/ingest";' in js
    assert 'const TOKEN = "t0k";' in js
    assert main(["serve", "--caido-script", "--port", "9999"]) == 0
    assert "http://127.0.0.1:9999/ingest" in capsys.readouterr().out


def test_token_required_when_set(tmp_path):
    live = Live(str(tmp_path / "live.jsonl"))
    box, started = {}, threading.Event()

    def ready(httpd):
        box["httpd"] = httpd
        started.set()
    t = threading.Thread(target=live_serve.serve, args=(live, lambda: "ok"),
                         kwargs={"port": 0, "token": "s3cret", "interval": 0.2, "ready": ready,
                                 "report": lambda s: None}, daemon=True)
    t.start()
    assert started.wait(10)
    port = box["httpd"].server_address[1]
    try:
        assert post(port, pair("GET", "/a"))[0] == 401
        assert post(port, pair("GET", "/a"), headers={"X-Proxy2model-Token": "nope"})[0] == 401
        assert post(port, pair("GET", "/a"), headers={"X-Proxy2model-Token": "s3cret"})[0] == 202
        assert post(port, pair("GET", "/a"), headers={"Authorization": "Bearer s3cret"})[0] == 202
    finally:
        box["httpd"].shutdown()
        t.join(10)
