"""`mcp`: serve built models to an AI agent over the Model Context Protocol (stdio).

Each tool runs the same command a researcher would type, so an agent gets exactly the answers
the CLI gives: cited, deterministic, no model call inside. It reads models under one output
folder and never builds, crawls or contacts anything.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys

from .. import __version__
from .common import _NAME_RE

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

_APP = {"type": "string", "description": "model name used at build time (the -w value)"}
TOOLS = [
    {"name": "list_models", "description": "The models built in this output folder, with their size and roles.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "query", "description": "Ask a model a factual question; every line cites evidence ids. "
                                     "Ask `help` first for what it answers (list-apis, reconcile, auth-surface, "
                                     "unknowns, provenance /path, ...). Questions it cannot answer are refused.",
     "inputSchema": {"type": "object", "required": ["app", "question"],
                     "properties": {"app": _APP, "question": {"type": "string"}}}},
    {"name": "bql", "description": "Filter and walk graph.db with BQL, e.g. `req.method:POST AND resp.code.gte:400`, "
                                   "`static-only`, `reach \"POST /api/checkout\"`. `help` prints the language.",
     "inputSchema": {"type": "object", "required": ["app", "expression"],
                     "properties": {"app": _APP, "expression": {"type": "string"},
                                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}}},
    {"name": "cross_role", "description": "What the lower-privileged role reached that only the higher one should.",
     "inputSchema": {"type": "object", "required": ["app", "low", "high"],
                     "properties": {"app": _APP, "low": {"type": "string"}, "high": {"type": "string"}}}},
    {"name": "builds", "description": "The builds of a model kept in graph.db, to pick two for diff.",
     "inputSchema": {"type": "object", "required": ["app"], "properties": {"app": _APP}}},
    {"name": "diff", "description": "What changed between two builds: new workflows, changed fingerprints, gone things.",
     "inputSchema": {"type": "object", "required": ["app"],
                     "properties": {"app": _APP,
                                    "from": {"type": "string", "description": "build id or label (default: previous)"},
                                    "to": {"type": "string", "description": "build id or label (default: latest)"}}}},
    {"name": "gaps", "description": "The model's open questions, ranked by how much resolving each would tell you.",
     "inputSchema": {"type": "object", "required": ["app"], "properties": {"app": _APP}}},
    {"name": "openapi", "description": "The observed API as an OpenAPI 3.0 document (JSON).",
     "inputSchema": {"type": "object", "required": ["app"], "properties": {"app": _APP}}},
]


class ToolError(Exception):
    pass


def _name(value, what: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ToolError(f"{what} must be letters, digits, '.', '_' or '-'")
    return value


def _text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{what} is required")
    return value


def _run(argv: list[str]) -> tuple[int, str]:
    """Run one CLI command and capture what it prints."""
    from .app import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:                     # argparse refusing an argument
            rc = e.code if isinstance(e.code, int) else 2
    text = out.getvalue()
    if err.getvalue().strip():
        text = (text + "\n" + err.getvalue()).strip()
    return rc or 0, text.strip()


def list_models(root: str) -> str:
    rows = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        path = os.path.join(root, name, "model.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        c = m.get("counts", {})
        rows.append(f"{name}: {c.get('endpoints', 0)} APIs, {c.get('routes', 0)} routes, "
                    f"{c.get('hosts', 0)} hosts, {len(m.get('evidence', []))} requests"
                    + (f", roles {', '.join(m.get('roles', []))}" if m.get("roles") else ""))
    return "\n".join(rows) or f"no models in {root} (build one with `proxy2model FILE -w NAME`)"


def call(tool: str, a: dict, root: str) -> tuple[bool, str]:
    """(ok, text) for one tool call. Options go before `--`, values after, so no value is read as a flag."""
    out = ["--out", root]
    if tool == "list_models":
        return True, list_models(root)
    app = _name(a.get("app"), "app")
    if tool == "query":
        argv = ["query", *out, "--", app, _text(a.get("question"), "question")]
    elif tool == "bql":
        limit = a.get("limit", 100)
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ToolError("limit must be 1 to 1000")
        argv = ["q", *out, "--limit", str(limit), "--", app, _text(a.get("expression"), "expression")]
    elif tool == "cross_role":
        argv = ["cross-role", *out, "--low", _name(a.get("low"), "low"), "--high", _name(a.get("high"), "high"),
                "--", app]
    elif tool == "builds":
        argv = ["builds", *out, "--", app]
    elif tool == "diff":
        refs = [_text(a[k], k) for k in ("from", "to") if a.get(k) is not None]
        if a.get("to") is not None and a.get("from") is None:
            refs = ["previous"] + refs
        argv = ["diff", *out, "--", app, *refs]
    elif tool == "gaps":
        argv = ["gaps", *out, "--", app]
    elif tool == "openapi":
        argv = ["openapi", *out, "--", app]
    else:
        raise ToolError(f"unknown tool {tool!r}")
    rc, text = _run(argv)
    return rc == 0, text or "(no output)"


def handle(msg: dict, root: str) -> dict | None:
    """One JSON-RPC message in, the response out (None for a notification)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None                                  # notifications/initialized and friends
    if method == "initialize":
        wanted = params.get("protocolVersion")
        result = {"protocolVersion": wanted if wanted in PROTOCOLS else PROTOCOLS[0],
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "proxy2model", "version": __version__},
                  "instructions": "Models of web apps built from captured traffic. Start with list_models, then "
                                  "query <app> help. Every answer cites evidence ids (ev_N); absence means the "
                                  "capture did not show it, not that it does not exist. Never call anything a "
                                  "vulnerability: these are leads to verify in an authorized session."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            ok, text = call(params.get("name"), params.get("arguments") or {}, root)
        except ToolError as e:
            ok, text = False, str(e)
        result = {"content": [{"type": "text", "text": text}], "isError": not ok}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve_stdio(root: str, stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg, root) if isinstance(msg, dict) else \
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    return 0


def cmd_mcp(args) -> int:
    root = os.path.abspath(args.out)
    print(f"proxy2model mcp: serving models in {root} over stdio", file=sys.stderr)
    return serve_stdio(root)
