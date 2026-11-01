"""`mcp`: an AI agent gets the same cited answers as the CLI, read-only, over stdio."""

import io
import json
import os

import pytest

from proxy2model.cli import main
from proxy2model.cli.mcp import PROTOCOLS, TOOLS, handle, serve_stdio

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(os.path.dirname(HERE), "samples")


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    o = tmp_path_factory.mktemp("mcp")
    for xml, role in (("burp-history-sample.xml", "user"), ("burp-history-admin-sample.xml", "admin")):
        assert main([os.path.join(SAMPLES, xml), "-w", "shop", "--role", role, "--out", str(o)]) == 0
    return str(o)


def call(out, name, **arguments):
    r = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}}, out)["result"]
    return r["isError"], r["content"][0]["text"]


def test_handshake_and_tools(out):
    r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}, out)["result"]
    assert r["protocolVersion"] == "2025-06-18" and "tools" in r["capabilities"]
    r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}, out)
    assert r["result"]["protocolVersion"] == PROTOCOLS[0]
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, out) is None
    names = [t["name"] for t in handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, out)["result"]["tools"]]
    assert names == [t["name"] for t in TOOLS]
    assert "error" in handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}, out)


def test_answers_match_the_cli(out):
    err, text = call(out, "list_models")
    assert not err and text.startswith("shop:") and "roles admin, user" in text
    err, text = call(out, "query", app="shop", question="list-apis")
    assert not err and "ev_" in text and "Model call: none" in text
    err, text = call(out, "cross_role", app="shop", low="user", high="admin")
    assert not err
    err, text = call(out, "bql", app="shop", expression="req.method:POST", limit=5)
    assert not err and "POST" in text
    err, text = call(out, "openapi", app="shop")
    assert not err and json.loads(text)["openapi"].startswith("3.0")
    for tool in ("builds", "gaps", "diff"):
        assert not call(out, tool, app="shop")[0], tool


def test_values_are_never_read_as_flags_or_paths(out):
    err, text = call(out, "query", app="shop", question="--out /etc")
    assert not err and "cannot answer" in text           # a question, refused as unknown, not an option
    assert call(out, "query", app="../shop", question="help") == (True, "app must be letters, digits, '.', '_' or '-'")
    assert call(out, "bql", app="shop", expression="x", limit=10 ** 6)[0]
    assert call(out, "query", app="nosuch", question="help")[0]          # missing model: an error, not a crash
    assert call(out, "nosuch_tool", app="shop")[0]


def test_stdio_loop(out):
    lines = "\n".join(json.dumps(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_models", "arguments": {}}},
    )) + "\nnot json\n"
    buf = io.StringIO()
    serve_stdio(out, io.StringIO(lines), buf)
    replies = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, None]
    assert replies[-1]["error"]["code"] == -32700
