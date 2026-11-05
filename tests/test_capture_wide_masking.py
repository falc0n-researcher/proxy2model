"""A cookie or credential value is masked wherever it appears in the capture, not only beside its name.

Found on a real Caido capture: page scripts send tracking ids to vendors (`fbp=…` in a URL,
`visUuid="…"` in a page) before the cookie that carries them is set, and an OTP request carried a
phone number inside escaped JSON.
"""

import json
import os
from xml.etree.ElementTree import Element, SubElement

from proxy2model import parse_items
from proxy2model.cli import main
from proxy2model.ingest.live import Live
from proxy2model.ingest.redact import redact_named

from test_caido import b64, caido_json, rec

FBP = "fb.1.1793913083850.123456789012345"
VWO = "D2DFAA0B1C2D3E4F5A6B7C8D9E0F1A2B3"


def outputs(out):
    text = ""
    for root, _, files in os.walk(out):
        for f in files:
            text += open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
    return text


CAPTURE = [
    # the vendor gets the id first, in its query string and in the page's inline script
    rec(1, "GET", "/tr", 200, query=f"id=1&fbp={FBP}&ev=PageView"),
    rec(2, "GET", "/", 200, rs_head="Content-Type: text/html\r\n",
        rs_body=f'<html><script>window.VWO.visUuid="{VWO}";</script></html>'),
    # only later does a request carry them as cookies
    rec(3, "GET", "/api/items", 200, rq_head=f"Cookie: _fbp={FBP}; _vwo_uuid_v2={VWO}\r\n"),
    rec(4, "POST", "/v4-sec/notification/send", 200, rq_head="Content-Type: application/json\r\n",
        rq_body=json.dumps({"payload": json.dumps({"recipient": {"callingCode": "91", "mobile": "9990001112"},
                                                   "hmac": "8922d8cd5d40ab410ee25008ec1aa47d"})})),
]


def test_a_value_sent_before_its_cookie_is_masked_everywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY2MODEL_FP_KEY", "ci")
    monkeypatch.setenv("PROXY2MODEL_OFFLINE", "1")
    out = tmp_path / "o"
    assert main([caido_json(tmp_path, CAPTURE), "-w", "shop", "--out", str(out)]) == 0
    text = outputs(out)
    for secret in (FBP, VWO, "9990001112", "8922d8cd5d40ab410ee25008ec1aa47d"):
        assert secret not in text, secret


def test_the_model_is_the_same_apart_from_the_masking(tmp_path):
    got = list(parse_items(caido_json(tmp_path, CAPTURE)))
    assert [e.method for e in got] == ["GET", "GET", "GET", "POST"]
    assert any(k == "fbp" for k, *_ in got[0].query_params)                 # the name stays, the value goes


def test_escaped_json_in_a_script_is_masked_by_name():
    text = r'var c="{\"token\":\"s3cr3tvalue123456\",\"password\":\"hunter2hunter2\",\"name\":\"bob\"}";'
    out = redact_named(text)
    assert "s3cr3tvalue123456" not in out and "hunter2hunter2" not in out
    assert r'\"name\":\"bob\"' in out                                          # an ordinary field is left alone


def test_personal_fields_are_masked_by_name():
    out = redact_named('{"mobile":"9990001112","phone_no":"9990001113","dob":"1990-01-01","panel":"left"}')
    for v in ("9990001112", "9990001113", "1990-01-01"):
        assert v not in out
    assert '"panel":"left"' in out


def item(path, cookie=""):
    el = Element("item")
    for tag, val in (("method", "GET"), ("host", "shop.test"), ("port", "443"), ("protocol", "https"),
                     ("path", path), ("status", "200"), ("mimetype", "")):
        SubElement(el, tag).text = val
    rq = f"GET {path} HTTP/1.1\r\nHost: shop.test\r\n" + (f"Cookie: {cookie}\r\n" if cookie else "") + "\r\n"
    SubElement(el, "request", {"base64": "true"}).text = b64(rq)
    SubElement(el, "response", {"base64": "true"}).text = b64("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}")
    return el


def test_browse_masks_what_it_saved_before_the_cookie_appeared(tmp_path):
    live = Live(str(tmp_path / "inputs" / "browse.jsonl"))
    live.ingest([item(f"/tr?fbp={FBP}")])
    live.flush()                                                              # saved while the value was unknown
    live.ingest([item("/api/items", cookie=f"_fbp={FBP}")])
    live.flush()
    live.finish()
    text = open(tmp_path / "inputs" / "browse.jsonl").read()
    assert FBP not in text and "fbp" in text
