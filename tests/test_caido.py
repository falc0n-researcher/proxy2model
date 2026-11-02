"""A Caido HTTP history export (JSON or CSV) builds the same kind of model as a Burp export.

The shape follows Caido's documented export: a JSON array of requests with the response nested
under `response`, or a CSV whose response columns are prefixed `response_`; `raw` is base64.
"""

import base64
import csv
import json
import os

from proxy2model import from_dict, parse_items
from proxy2model.cli import main

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def rec(i, method, path, status, rq_head="", rq_body="", rs_head="Content-Type: application/json\r\n",
        rs_body="{}", query="", source="intercept", tls=True):
    target = path + ("?" + query if query else "")
    raw_rq = f"{method} {target} HTTP/1.1\r\nHost: shop.test\r\n{rq_head}\r\n{rq_body}"
    raw_rs = f"HTTP/1.1 {status} OK\r\n{rs_head}\r\n{rs_body}"
    return {"id": i, "host": "shop.test", "method": method, "path": path, "length": len(raw_rq),
            "port": 443 if tls else 80, "raw": b64(raw_rq), "is_tls": tls, "query": query,
            "file_extension": None, "source": source, "alteration": "none", "edited": False,
            "parent_id": None, "created_at": "2026-10-12T10:00:00Z",
            "response": {"id": i, "status_code": status, "raw": b64(raw_rs), "length": len(raw_rs),
                         "alteration": "none", "edited": False, "parent_id": None,
                         "created_at": "2026-10-12T10:00:00Z"}}


SHOP = [
    rec(1, "GET", "/", 200, rs_head="Content-Type: text/html\r\nSet-Cookie: sid=SECRETCOOKIEVALUE123456; HttpOnly\r\n",
        rs_body='<html><script src="/app.js"></script></html>'),
    rec(2, "GET", "/app.js", 200, rs_head="Content-Type: application/javascript\r\n",
        rs_body='fetch("/api/orders");fetch("/api/hidden/audit")'),
    rec(3, "POST", "/api/orders", 201, query="page=2",
        rq_head=f"Authorization: Bearer {JWT}\r\nCookie: sid=SECRETCOOKIEVALUE123456\r\nContent-Type: application/json\r\n",
        rq_body='{"item": 7, "email": "alice@corp.example"}', rs_body='{"id": 9}'),
    rec(4, "POST", "/login", 200, rq_head="Content-Type: application/x-www-form-urlencoded\r\n",
        rq_body="user=alice&password=hunter2hunter2", rs_body='{"ok": true}', source="replay"),
]
NO_RESPONSE = {**rec(5, "GET", "/never-answered", 200), "response": None}


def caido_json(tmp_path, records, name="export.json"):
    p = tmp_path / name
    p.write_text(json.dumps(records))
    return str(p)


def caido_csv(tmp_path, records, name="export.csv"):
    cols = [k for k in records[0] if k != "response"] + ["response_" + k for k in records[0]["response"]]
    p = tmp_path / name
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in records:
            flat = {**{k: v for k, v in r.items() if k != "response"},
                    **{"response_" + k: v for k, v in (r["response"] or {}).items()}}
            w.writerow(["" if flat.get(c) is None else str(flat.get(c)).lower() if isinstance(flat.get(c), bool)
                        else flat.get(c) for c in cols])
    return str(p)


def build(tmp_path, monkeypatch, path):
    monkeypatch.setenv("PROXY2MODEL_FP_KEY", "ci")
    monkeypatch.setenv("PROXY2MODEL_OFFLINE", "1")
    out = tmp_path / "o"
    assert main([path, "-w", "shop", "--out", str(out)]) == 0
    return out, from_dict(json.load(open(out / "shop" / "model.json")))


def test_a_caido_json_export_builds_a_model(tmp_path, monkeypatch):
    _, m = build(tmp_path, monkeypatch, caido_json(tmp_path, SHOP + [NO_RESPONSE]))
    labels = {n.label for n in m.nodes.values()}
    assert {"POST /api/orders", "/", "app.js"} <= labels
    assert "* /api/hidden/audit" in labels                              # named in the script, never called
    assert m.nodes["endpoint:POST:shop.test:/api/orders"].attrs["credentials"]
    assert m.stats["items"] == 5 and m.stats["parsed"] == 4 and m.stats["skipped"] == 1


def test_a_caido_csv_export_builds_the_same_model(tmp_path, monkeypatch):
    _, m = build(tmp_path, monkeypatch, caido_csv(tmp_path, SHOP))
    labels = {n.label for n in m.nodes.values()}
    assert {"POST /api/orders", "/", "app.js"} <= labels
    assert m.stats["parsed"] == 4


def test_query_and_tls_come_from_their_own_fields(tmp_path):
    ex = [e for e in parse_items(caido_json(tmp_path, SHOP)) if e.method == "POST" and "orders" in e.path_template]
    assert ex and ex[0].status == 201
    assert any(k == "page" for k, *_ in ex[0].query_params)
    plain = list(parse_items(caido_json(tmp_path, [rec(1, "GET", "/", 200, tls=False)], name="plain.json")))
    assert plain[0].port == 80 and plain[0].scheme == "http"


def test_no_secret_value_survives_a_caido_export(tmp_path, monkeypatch):
    out, _ = build(tmp_path, monkeypatch, caido_json(tmp_path, SHOP))
    for root, _, files in os.walk(out):
        for f in files:
            if f.endswith(".db"):
                continue
            body = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            for secret in (JWT, "SECRETCOOKIEVALUE123456", "hunter2hunter2", "alice@corp.example"):
                assert secret not in body, (f, secret)


def test_caido_source_filters_like_a_tool_column(tmp_path):
    stats: dict = {}
    got = list(parse_items(caido_json(tmp_path, SHOP), stats=stats, skip_tools=("Replay",)))
    assert len(got) == 3 and stats["filtered"] == 1
    assert stats["tools"] == {"intercept": 3, "replay": 1}


def test_a_logger_csv_is_still_a_logger_csv(tmp_path):
    p = tmp_path / "logger.csv"
    p.write_text("Method,Host,Path,Request,Response\nGET,shop.test,/,"
                 + b64("GET / HTTP/1.1\r\nHost: shop.test\r\n\r\n") + ","
                 + b64("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html></html>") + "\n")
    assert len(list(parse_items(str(p)))) == 1
