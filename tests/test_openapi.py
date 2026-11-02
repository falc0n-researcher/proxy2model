"""Parameter value types are inferred before masking, and the model exports as OpenAPI 3.0."""

import json

import pytest

from proxy2model import from_dict, parse_items
from proxy2model.cli import main
from proxy2model.ingest.infer import value_type
from proxy2model.core.model import build
from proxy2model.export.openapi import to_openapi

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


@pytest.mark.parametrize("value,expected", [
    (JWT, "jwt"),
    ("3f2b8c1e-9d4a-4b7e-8f1a-2c3d4e5f6a7b", "uuid"),
    ("alice@shop.test", "email"),
    ("42", "integer"),
    ("-7", "integer"),
    ("3.14", "number"),
    ("true", "boolean"),
    ("dGhpcyBpcyBhIHRlc3Q=", "base64"),
    ("SGVsbG9Xb3JsZDEyMw", "base64"),
    ("admin", "string"),
    ("hello world", "string"),
    ("ABCDEFGHIJKL", "string"),         # base64-valid by accident, but no mix: a word
    ("", None),
    (None, None),
])
def test_value_type_waterfall(value, expected):
    assert value_type(value) == expected


def h(**kw):
    return [{"name": k.replace("_", "-"), "value": v} for k, v in kw.items()]


def entry(method, url, status, body=None):
    e = {"startedDateTime": "2026-10-12T10:00:00Z",
         "request": {"method": method, "url": url, "httpVersion": "HTTP/1.1", "headers": [], "queryString": []},
         "response": {"status": status, "statusText": "OK",
                      "headers": h(Content_Type="application/json"),
                      "content": {"mimeType": "application/json", "text": "{}"}}}
    if body is not None:
        e["request"]["headers"] = h(Content_Type="application/json")
        e["request"]["postData"] = {"mimeType": "application/json", "text": json.dumps(body)}
    return e


ENTRIES = [
    entry("GET", "https://api.shop.test/api/users/101?page=2&email=bob@shop.test", 200),
    entry("GET", "https://api.shop.test/api/users/202?page=3", 200),
    entry("GET", "https://api.shop.test/api/users/303", 404),
    entry("POST", "https://api.shop.test/api/orders", 201,
          body={"item": "3f2b8c1e-9d4a-4b7e-8f1a-2c3d4e5f6a7b", "qty": 2, "gift": True,
                "tags": ["a"], "ship": {"zip": "10001"}}),
    entry("GET", "https://api.shop.test/api/a/1/b/2", 200),
]


@pytest.fixture
def model(tmp_path):
    p = tmp_path / "s.har"
    p.write_text(json.dumps({"log": {"version": "1.2", "creator": {"name": "t"}, "entries": ENTRIES}}))
    exchanges = list(parse_items(str(p)))
    return exchanges, build(exchanges, "shop")


def test_types_survive_masking_values_do_not(model):
    exchanges, m = model
    first = exchanges[0]
    assert ("query", "email", "email") in first.param_types
    assert ("query", "page", "integer") in first.param_types
    # the raw email never reaches the exchange; only its label does
    assert "bob@shop.test" not in json.dumps(first.to_record())
    params = {n.label: n.attrs["types"] for n in m.nodes.values() if n.type == "parameter"}
    assert params["page"] == ["integer"]
    assert params["$.item"] == ["uuid"]
    assert params["$.gift"] == ["boolean"]


def test_openapi_document(model):
    _, m = model
    spec = to_openapi(m)
    assert spec["openapi"].startswith("3.0")
    assert spec["servers"] == [{"url": "https://api.shop.test"}]

    users = spec["paths"]["/api/users/{id}"]["get"]
    names = {(p["in"], p["name"]): p["schema"] for p in users["parameters"]}
    assert ("path", "id") in names
    assert names[("query", "page")] == {"type": "integer"}
    assert names[("query", "email")] == {"type": "string", "format": "email"}
    assert set(users["responses"]) == {"200", "404"}
    assert users["x-proxy2model-evidence"]

    body = spec["paths"]["/api/orders"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert body["properties"]["item"] == {"type": "string", "format": "uuid"}
    assert body["properties"]["qty"] == {"type": "integer"}
    assert body["properties"]["tags"]["type"] == "array"
    assert body["properties"]["ship"]["properties"]["zip"] == {"type": "integer"}

    # repeated placeholders get unique names, as OpenAPI requires
    twice = [k for k in spec["paths"] if k.startswith("/api/a/")]
    assert twice == ["/api/a/{id}/b/{id2}"]


def test_openapi_cli_round_trips_through_model_json(tmp_path, capsys):
    p = tmp_path / "s.har"
    p.write_text(json.dumps({"log": {"version": "1.2", "creator": {"name": "t"}, "entries": ENTRIES}}))
    out = str(tmp_path / "out")
    assert main([str(p), "-w", "shop", "--out", out]) == 0
    capsys.readouterr()
    target = tmp_path / "spec.json"
    assert main(["openapi", "shop", "--out", out, "-o", str(target)]) == 0
    spec = json.loads(target.read_text())
    assert "/api/users/{id}" in spec["paths"]
    # model.json keeps the type labels, so a reload exports the same schemas
    with open(f"{out}/shop/model.json") as f:
        assert to_openapi(from_dict(json.load(f)))["paths"] == spec["paths"]


def har(tmp_path, entries):
    p = tmp_path / "t.har"
    p.write_text(json.dumps({"log": {"version": "1.2", "entries": entries}}))
    return build(list(parse_items(str(p))), name="t")


def test_response_fields_become_response_schemas(tmp_path):
    e = entry("GET", "https://api.shop.test/api/me", 200)
    e["response"]["content"]["text"] = json.dumps({
        "id": 7, "email": "bob@shop.test", "admin": False, "score": 1.5, "token": JWT,
        "tags": [{"name": "x"}], "byUser": {"alice@shop.test": 1}, "note": None})
    m = har(tmp_path, [e])
    doc = to_openapi(m)
    schema = doc["paths"]["/api/me"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    props = schema["properties"]
    assert props["id"] == {"type": "integer"} and props["admin"] == {"type": "boolean"}
    assert props["score"] == {"type": "number"} and props["email"]["format"] == "email"
    assert props["tags"]["items"]["properties"]["name"]["type"] == "string"
    assert props["byUser"]["additionalProperties"] == {"type": "integer"}   # a key that is a value: any key
    assert "note" not in props                                            # null says nothing about a type
    text = json.dumps(doc) + json.dumps(m.nodes, default=str)
    assert "bob@shop.test" not in text and "alice@shop.test" not in text and JWT not in text


def test_bot_detection_posts_are_not_apis(tmp_path):
    akamai = entry("POST", "https://www.shop.test/aB3dE/Xy9/dyB-VF8vAQ/CX/1gGXUINSE", 201)
    akamai["request"]["postData"] = {"mimeType": "text/plain", "text": '{"sensor_data":"2;0;3;..."}'}
    cf = entry("POST", "https://www.shop.test/cdn-cgi/challenge-platform/h/b/jsd/r/abc", 200)
    m = har(tmp_path, [akamai, cf, entry("GET", "https://www.shop.test/api/real", 200)])
    labels = {n.label for n in m.nodes.values() if n.type == "endpoint"}
    assert labels == {"GET /api/real"}
    assert m.stats["bot_detection_requests"] == 2


def test_a_variable_base_url_is_not_pinned_to_the_page_host(tmp_path):
    js = entry("GET", "https://www.shop.test/app.js", 200)
    js["response"]["headers"] = h(Content_Type="application/javascript")
    js["response"]["content"] = {"mimeType": "application/javascript", "text":
        'fetch(`${this.apiHost}/v1/accounts:signInWithPassword`, {method: "POST"}); fetch("/api/orders")'}
    m = har(tmp_path, [js])
    eps = {n.label: n.attrs["host"] for n in m.nodes.values() if n.type == "endpoint"}
    assert eps["POST {base}/v1/accounts:signInWithPassword"] == "{base}"
    assert eps["* /api/orders"] == "www.shop.test"
    assert all("{base}" not in p for p in to_openapi(m, include_static=True)["paths"])
