"""
Export a model's API endpoints as an OpenAPI 3.0 document.

Only what the capture shows goes in: each operation is an endpoint the traffic
reached (or, with `include_static`, one the client code references), its
parameters are the names seen on the wire, and their schemas come from the
type each raw value had (see infer.py). Response codes are the statuses
observed; their bodies are not modelled. Every operation carries the evidence
ids that prove it, so a reader can go from the spec back to the request.

Paths are host-independent in OpenAPI, so each operation lists the server(s)
it was seen on.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..core.model import Model
from ..ingest.extract import VAR_BASE

OPENAPI_VERSION = "3.0.3"
_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_PLACEHOLDER_RE = re.compile(r"\{([^/{}]*)\}")

# schema for each inferred value type
_TYPE_SCHEMA = {
    "jwt": {"type": "string", "description": "JSON Web Token"},
    "uuid": {"type": "string", "format": "uuid"},
    "email": {"type": "string", "format": "email"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "base64": {"type": "string", "format": "byte"},
    "string": {"type": "string"},
}

# schema for each path placeholder redact.py writes
_PLACEHOLDER_SCHEMA = {
    "id": {"type": "string", "description": "numeric or opaque identifier"},
    "uuid": {"type": "string", "format": "uuid"},
    "hash": {"type": "string", "pattern": "^[0-9a-fA-F]+$"},
    "email": {"type": "string", "format": "email"},
    "jwt": {"type": "string", "description": "JSON Web Token"},
}


def schema_for(types: list[str]) -> dict:
    """One schema for the types a parameter was seen with; mixed types become a oneOf."""
    schemas = []
    for t in sorted(set(types or [])):
        s = _TYPE_SCHEMA.get(t, _TYPE_SCHEMA["string"])
        if s not in schemas:
            schemas.append(dict(s))
    if not schemas:
        return {"type": "string"}
    if len(schemas) == 1:
        return schemas[0]
    return {"oneOf": schemas}


def _path_params(path: str) -> tuple[str, list[dict]]:
    """Rewrite placeholders to unique names (`/a/{id}/b/{id}` -> `{id}`, `{id2}`) and describe them."""
    seen: dict[str, int] = defaultdict(int)
    params: list[dict] = []

    def rename(m: re.Match) -> str:
        base = re.sub(r"[^A-Za-z0-9_]", "", m.group(1)) or "param"
        seen[base] += 1
        name = base if seen[base] == 1 else f"{base}{seen[base]}"
        params.append({"name": name, "in": "path", "required": True,
                       "schema": dict(_PLACEHOLDER_SCHEMA.get(base, {"type": "string"}))})
        return "{" + name + "}"

    return _PLACEHOLDER_RE.sub(rename, path), params


_TOKEN_RE = re.compile(r"\.([^.\[\]]+)|\[(\d*)\]")


def _json_schema(fields: list[tuple[str, list[str]]]) -> dict:
    """Rebuild a nested object schema from JSONPath-style names (`$.user.tags[]`)."""
    root: dict = {}
    for name, types in fields:
        tokens = [(m.group(1), m.group(2)) for m in _TOKEN_RE.finditer(name[1:])]
        if not tokens:                          # a bare scalar body (`"abc"`, `42`)
            root.update(schema_for(types))
            continue
        node = root
        for pos, (key, idx) in enumerate(tokens):
            last = pos == len(tokens) - 1
            if key == "{key}":                  # a map keyed by values (ids, emails): any key
                node.setdefault("type", "object")
                node = node.setdefault("additionalProperties", {})
            elif key is not None:
                node.setdefault("type", "object")
                props = node.setdefault("properties", {})
                node = props.setdefault(key, {})
            else:
                node.setdefault("type", "array")
                node = node.setdefault("items", {})
            if last and "type" not in node:
                node.update(schema_for(types))
    return root or {"type": "object"}


def _request_body(body: list[tuple[str, list[str]]]) -> dict | None:
    if not body:
        return None
    json_fields = [(n, t) for n, t in body if n.startswith("$")]
    form_fields = [(n, t) for n, t in body if not n.startswith("$")]
    content: dict = {}
    if json_fields:
        content["application/json"] = {"schema": _json_schema(json_fields)}
    if form_fields:
        content["application/x-www-form-urlencoded"] = {"schema": {
            "type": "object",
            "properties": {n: schema_for(t) for n, t in sorted(form_fields)},
        }}
    return {"content": content}


def _responses(statuses: list, fields: dict[str, dict[str, list[str]]]) -> dict:
    """One response per observed status; a JSON schema where a JSON body was seen with it."""
    out = {}
    for st in sorted({s for s in statuses if s is not None}):
        out[str(st)] = {"description": "Observed"}
        if fields.get(str(st)):
            out[str(st)]["content"] = {"application/json": {"schema": _json_schema(sorted(fields[str(st)].items()))}}
    return out or {"default": {"description": "No response observed"}}


def _op_id(method: str, path: str, taken: set[str]) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", path) if w]
    base = method + "".join(w[:1].upper() + w[1:] for w in words) or method
    oid, n = base, 1
    while oid in taken:
        n += 1
        oid = f"{base}{n}"
    taken.add(oid)
    return oid


def _server_urls(m: Model, host: str) -> list[str]:
    """Every origin the capture reached `host` on, from the host node's schemes and ports."""
    hn = m.nodes.get(f"host:{host}")
    schemes = (hn.attrs.get("schemes") if hn else None) or ["https"]
    ports = (hn.attrs.get("ports") if hn else None) or [None]
    default = {"http": 80, "https": 443}
    urls = set()
    for sch in schemes:
        for port in ports:
            if port is None or port == default.get(sch):
                urls.add(f"{sch}://{host}")
            elif port not in default.values():          # http:443 / https:80 are pairing artefacts
                urls.add(f"{sch}://{host}:{port}")
    return sorted(urls) or [f"https://{host}"]


def to_openapi(m: Model, host: str | None = None, include_static: bool = False,
               title: str | None = None, version: str = "observed") -> dict:
    """The model's endpoints as an OpenAPI 3.0 document (a plain dict, ready for json.dump)."""
    params_of: dict[str, list] = defaultdict(list)
    for e in m.edges:
        if e.type == "USES_PARAMETER" and e.dst in m.nodes:
            params_of[e.src].append(m.nodes[e.dst])

    # (path, method) -> the endpoint nodes behind it, across hosts
    ops: dict[tuple[str, str], list] = defaultdict(list)
    for n in m.nodes.values():
        if n.type != "endpoint":
            continue
        if host and n.attrs.get("host") != host:
            continue
        if n.attrs.get("host") == VAR_BASE:        # its server is a variable in the code: unknown
            continue
        state = n.attrs.get("api_state")
        if state == "STATIC_ONLY" and not include_static:
            continue
        method = (n.attrs.get("method") or "").lower()
        if method == "*" or not method:
            method = "get"                  # a reference whose method the code did not name
        if method not in _METHODS:
            continue
        ops[(n.attrs.get("path") or "/", method)].append(n)

    paths: dict[str, dict] = {}
    hosts: set[str] = set()
    taken: set[str] = set()
    for (raw_path, method), nodes in sorted(ops.items()):
        path, path_params = _path_params(raw_path if raw_path.startswith("/") else "/" + raw_path)
        query: dict[str, list[str]] = defaultdict(list)
        body: dict[str, list[str]] = defaultdict(list)
        statuses, evidence, creds, states, op_hosts = [], set(), set(), set(), set()
        resp_fields: dict[str, dict[str, list[str]]] = {}
        method_known = True
        for n in nodes:
            op_hosts.add(n.attrs.get("host"))
            statuses.extend(n.attrs.get("statuses") or [])
            evidence.update(n.evidence)
            creds.update(n.attrs.get("credentials") or [])
            states.add(n.attrs.get("api_state"))
            for st, fs in (n.attrs.get("response_fields") or {}).items():
                for fname, types in fs.items():
                    merged = resp_fields.setdefault(st, {}).setdefault(fname, [])
                    merged.extend(t for t in types if t not in merged)
            if n.attrs.get("method_known") is False:
                method_known = False
            for p in params_of.get(n.id, []):
                bucket = query if p.attrs.get("location") == "query" else body
                bucket[p.label].extend(p.attrs.get("types") or [])
        hosts.update(h for h in op_hosts if h)

        op: dict = {
            "operationId": _op_id(method, path, taken),
            "summary": f"{method.upper()} {path}",
            "parameters": path_params + [
                {"name": name, "in": "query", "required": False, "schema": schema_for(types)}
                for name, types in sorted(query.items())
            ],
            "responses": _responses(statuses, resp_fields),
            "servers": [{"url": u} for h in sorted(h for h in op_hosts if h) for u in _server_urls(m, h)],
            "x-proxy2model-api-state": sorted(s for s in states if s),
            "x-proxy2model-evidence": sorted(evidence),
        }
        rb = _request_body(sorted(body.items()))
        if rb:
            op["requestBody"] = rb
        if creds:
            op["x-proxy2model-credentials"] = sorted(creds)
        if not method_known:
            op["x-proxy2model-method-known"] = False
        if not op["parameters"]:
            del op["parameters"]
        paths.setdefault(path, {})[method] = op

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": title or f"{m.name} (observed)",
            "version": version,
            "description": "Generated by proxy2model from captured traffic. Only observed "
                           "endpoints, parameters, status codes and response fields are included.",
        },
        "servers": [{"url": u} for h in sorted(hosts) for u in _server_urls(m, h)],
        "paths": paths,
    }
