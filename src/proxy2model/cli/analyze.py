"""Commands that read a built model: query, q, graph, gaps, changes, openapi and the rest."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

from ..atomic import atomic_write
from ..ingest.parse import parse_items
from ..core.model import build, from_dict, cross_role
from ..core.context import SOURCE, query as run_query
from ..report.animate import render_terminal, write_svg
from ..core.graph import (
    ReasonGraph, reason_graph, to_graphml, to_cypher, to_graph_json,
)
from ..core.methodology import (
    investigation_plan, methodology_package, rank_gaps,
    METHODOLOGY_PROMPT, FALSIFY_PROMPT,
)
from ..core.changes import diff_models
from ..export.openapi import to_openapi
from ..db import store, bql
from . import ui
from .common import (
    _init_key, _db_path, _model_path, _reload,
)


def cmd_q(args) -> int:
    path = _db_path(args)
    if path is None:
        return 2
    try:
        conn = bql.connect(path)
    except (ValueError, sqlite3.Error) as e:
        print(f"could not open {path}: {e}", file=sys.stderr)
        return 2

    def run_one(text: str) -> int:
        try:
            res = bql.run_query(conn, text, limit=args.limit)
        except (bql.BQLError, sqlite3.Error) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(bql.render_json(res) if args.format == "json" else bql.render_text(res))
        return 0

    try:
        if args.query:
            return run_one(" ".join(args.query))
        print(f"proxy2model q · {args.webapp} · graph.db — `help` for the language, Ctrl-D to exit")
        while True:
            try:
                line = input("bql> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if line in ("exit", "quit"):
                return 0
            if line:
                run_one(line)
    finally:
        conn.close()


def cmd_query(args) -> int:
    path = _model_path(args)
    if path is None:
        return 2
    m = _reload(path)
    if m is None:
        return 2
    print(run_query(m, args.question))
    return 0


def cmd_crossrole(args) -> int:
    path = _model_path(args)
    if path is None:
        return 2
    m = _reload(path)
    if m is None:
        return 2
    missing = [r for r in (args.low, args.high) if r not in m.roles]
    if missing:
        print(f"role(s) not in this model: {', '.join(missing)} "
              f"(model has: {', '.join(sorted(m.roles)) or 'none'}).\n"
              f"Build each capture with --role <name> into the same --out/--webapp.",
              file=sys.stderr)
        return 2
    result = cross_role(m, args.low, args.high)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    def show(title, items):
        print(f"{title} ({len(items)})")
        for s in items:
            ev = ", ".join(f"ev_{e}" for e in s["evidence"])
            st = " ".join(f"{r}={v}" for r, v in s["statuses"].items())
            print(f"  {s['endpoint']:<44} {ev}  {st}")
            print(f"    unknown: {s['unknown']} · next: {s['next']}")
        print()

    show(f"'{args.low}' reached privileged-looking endpoints", result["low_reached_privileged"])
    show(f"'{args.high}' reached, '{args.low}' never tried", result["high_only"])
    show("both roles got 2xx", result["shared_same_success"])
    print("Each is a hypothesis, not a finding.")
    return 0


def cmd_osint(args) -> int:
    from ..recon import osint as osint_mod

    host = args.host.strip().lower().replace("https://", "").replace("http://", "")
    host = host.split("/")[0].split(":")[0]
    if not re.match(r"^[a-z0-9.\-]{1,253}$", host) or "." not in host:
        print(f"not a hostname: {args.host!r}", file=sys.stderr)
        return 2
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        print(f"{host} is an IP address — osint needs a hostname "
              "(DNS, certificate transparency and RDAP are domain lookups)", file=sys.stderr)
        return 2
    # Active recon reaches out to the target and to public services. Gate it.
    if not (args.yes or os.environ.get("PROXY2MODEL_OSINT_CONSENT") == "1"):
        print(
            "osint sends live requests to the target and to public services "
            "(DNS, TLS, HTTP" + (", TCP ports" if args.ports else "") + ", CT logs, RDAP).\n"
            f"Only run this against hosts you are authorized to test.\n"
            f"  target: {host}\n"
            "Re-run with --yes to confirm you have authorization.",
            file=sys.stderr)
        return 2

    result = osint_mod.run(host, timeout=args.timeout, want_ports=args.ports,
                           want_subdomains=not args.no_subdomains)
    blob = json.dumps(result.to_dict(), indent=2)
    saved = None
    try:
        if args.webapp:
            outdir = os.path.join(args.out, args.webapp)
            os.makedirs(outdir, exist_ok=True)
            saved = os.path.join(outdir, "osint.json")
            with atomic_write(saved) as f:
                f.write(blob)
        if args.out_file:
            with atomic_write(args.out_file) as f:
                f.write(blob)
            saved = args.out_file
    except OSError as e:
        print(f"could not write osint report: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(blob)
    else:
        print(osint_mod.render_text(result))
    if saved:
        print(f"\nwrote {saved}", file=sys.stderr)
        if args.webapp:
            mp = os.path.join(args.out, args.webapp, "model.json")
            if os.path.exists(mp):
                try:
                    with open(mp, encoding="utf-8") as f:
                        model = from_dict(json.load(f))
                    dbs = store.write_db(model, os.path.join(args.out, args.webapp,
                                                             store.DB_NAME),
                                         osint=result.to_dict())
                    if dbs.get("damaged"):
                        print(f"warning: graph.db was damaged; kept it aside as {dbs['damaged']}",
                              file=sys.stderr)
                    print(f"graph.db updated ({dbs['external_nodes']} external nodes, "
                          f"{dbs['osint_runs']} recon run(s) stored)", file=sys.stderr)
                except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
                    print(f"could not update graph.db: {e}", file=sys.stderr)
            print("run the build again for this webapp to fold it into "
                  "report.html and context.json.", file=sys.stderr)
    return 0


def _render_reason(rg, m) -> str:
    """A compact text overview of the graph's reasoning views."""
    L = [f"{m.name} — graph reasoning  ({len(m.nodes)} nodes, {len(m.edges)} edges)", ""]
    comms = rg.communities()
    L.append(f"Communities ({len(comms)}) — functional areas")
    for c in comms[:8]:
        kinds = ", ".join(f"{v} {k}" for k, v in c["kinds"].items())
        L.append(f"  {c['id']}  '{c['name']}'  {c['size']} nodes  ({kinds})")
    L.append("")
    L.append("Hubs — the load-bearing nodes")
    for h in rg.hubs(8):
        L.append(f"  {h['degree']:>3}  {h['type']:<12} {h['label']}")
    L.append("")
    zones = rg.trust_zones()
    L.append("Trust zones — how identity reaches the surface")
    for z, rows in zones.items():
        L.append(f"  {z:<18} {len(rows)} endpoint(s)")
    L.append("")
    coup = rg.coupling()
    L.append(f"Coupling — {len(coup['cross_community'])} cross-area edge(s), "
             f"{len(coup['to_third_party'])} to third parties")
    L.append("")
    L.append("Source: model graph · Model call: none")
    return "\n".join(L)


def cmd_graph(args) -> int:
    path = _model_path(args)
    if path is None:
        return 2
    m = _reload(path)
    if m is None:
        return 2
    rg = ReasonGraph(m)

    if args.reach or args.blast or args.touched_by:
        target = (args.reach or args.blast or args.touched_by).lower()
        # rank: prefer a label hit over an id hit, a meaningful node over a
        # parameter/operation/cookie, and the shortest label among equals
        leaf = ("parameter", "operation", "cookie")
        scored = []
        for nid, n in m.nodes.items():
            lbl = n.label.lower()
            if target in lbl:
                rank = 0 if lbl == target else 1
            elif target in nid.lower():
                rank = 2
            else:
                continue
            scored.append(((rank, n.type in leaf, len(n.label)), nid))
        if not scored:
            print(f"no node matches {target!r}", file=sys.stderr)
            return 2
        scored.sort()
        nid = scored[0][1]
        if args.reach:
            result = rg.reach(nid)
        elif args.blast:
            result = rg.blast(nid, depth=args.depth)
        else:
            result = rg.touched_by(nid, depth=args.depth)
        print(json.dumps(result, indent=2))
        return 0

    fmt = args.format
    if fmt == "graphml":
        out = to_graphml(m)
    elif fmt == "cypher":
        out = to_cypher(m)
    elif fmt == "json":
        out = json.dumps(to_graph_json(m), indent=2)
    elif fmt == "reason":
        out = json.dumps(reason_graph(m), indent=2)
    else:
        out = _render_reason(rg, m)

    if args.out_file:
        try:
            with atomic_write(args.out_file) as f:
                f.write(out)
        except OSError as e:
            print(f"could not write {args.out_file}: {e}", file=sys.stderr)
            return 2
        print(f"wrote {args.out_file}", file=sys.stderr)
    else:
        print(out)
    return 0


def _render_plan(plan: dict) -> str:
    p = plan["posture"]
    L = [f"{plan['app']} — investigation scaffold  (scope: {', '.join(plan['scope']) or '?'})", ""]
    L.append(f"{p['endpoints']} endpoints · {p['feature_areas']} feature areas · "
             f"roles: {', '.join(p['roles']) or 'none'}")
    L.append(f"{p['static_only']} code-only · {p['privileged']} privileged · "
             f"{p['credentialed']} credentialed · {p['open_questions']} open questions")
    L.append("")
    L.append("RECON — establish first")
    for r in plan["recon"]:
        L.append(f"  • {r['step']}")
        L.append(f"      why: {r['why']}")
        L.append(f"      how: {r['how']}")
    L.append("")
    L.append("LINES OF INQUIRY — by leverage")
    for ln in plan["lines_of_inquiry"]:
        if not ln["endpoints"]:
            continue
        L.append(f"  [{ln['leverage']:>2}] {ln['area']} — {ln['why_it_matters']}")
        if ln["reach"]:
            L.append(f"       reached {'; '.join(ln['reach'])}")
        for s in ln["signals"][:5]:
            ev = ", ".join(f"ev_{i}" for i in s["evidence"])
            L.append(f"       - {s['endpoint']}: {s['observation']}  [{ev}]")
            L.append(f"         → {s['question']}")
            L.append(f"         next: {s['next']}")
        for q in ln["open_questions"][:4]:
            ent = f"{q['entity']}: " if q.get("entity") else ""
            L.append(f"       ? {ent}{q['unknown']} — {q['to_find_out']}")
        L.append("")
    if plan["watch"]["third_party_trust"]:
        L.append("WATCH — trust leaving the app")
        for e in plan["watch"]["third_party_trust"][:8]:
            L.append(f"  {e['from']} → {e['to']}  ({e['edge'].lower()})")
        L.append("")
    L.append("This is a scaffold, not the methodology. Hand it to an AI with "
             "`--prompt` to reason a sequenced, target-specific plan.")
    L.append("Source: model graph · Model call: none")
    return "\n".join(L)


def cmd_methodology(args) -> int:
    path = _model_path(args)
    if path is None:
        return 2
    m = _reload(path)
    if m is None:
        return 2
    if args.json:
        out = json.dumps(investigation_plan(m), indent=2)
    elif args.prompt:
        pkg = methodology_package(m)
        out = ("\n".join(METHODOLOGY_PROMPT) + "\n\n"
               + "MODEL AND SCAFFOLD (JSON):\n```json\n"
               + json.dumps({"plan_scaffold": pkg["plan_scaffold"],
                             "model": pkg["model"]}, separators=(",", ":")) + "\n```")
    else:
        out = _render_plan(investigation_plan(m))
    if args.out_file:
        try:
            with atomic_write(args.out_file) as f:
                f.write(out)
        except OSError as e:
            print(f"could not write {args.out_file}: {e}", file=sys.stderr)
            return 2
        print(f"wrote {args.out_file}", file=sys.stderr)
    else:
        print(out)
    return 0


def cmd_openapi(args) -> int:
    path = _model_path(args)
    if path is None:
        return 2
    m = _reload(path)
    if m is None:
        return 2
    spec = to_openapi(m, host=args.host, include_static=args.include_static)
    text = json.dumps(spec, indent=2)
    if args.output in (None, "-"):
        print(text)
        return 0
    try:
        with atomic_write(args.output) as f:
            f.write(text + "\n")
    except OSError as e:
        print(ui.error(f"could not write {args.output}: {e}"), file=sys.stderr)
        return 2
    print(ui.ok(f"wrote {args.output}  ({len(spec['paths'])} paths, "
                f"{sum(len(v) for v in spec['paths'].values())} operations)"), file=sys.stderr)
    return 0


def cmd_gaps(args) -> int:
    path = _model_path(args)
    if path is None:
        return 2
    m = _reload(path)
    if m is None:
        return 2
    g = rank_gaps(m)
    if args.json:
        print(json.dumps(g, indent=2))
        return 0
    print(f"{g['app']} — gaps, ranked by how much resolving each improves the picture")
    print()
    for i, gap in enumerate(g["gaps"], 1):
        print(f"#{i}  [{gap['leverage']:>2}]  {gap['entity']}")
        print(f"      unknown: {gap['unknown']}")
        print(f"      next:    {gap['next']}")
    print()
    print("absence = a gap in observation, never a statement about the target")
    print(SOURCE)
    return 0


def cmd_changes(args) -> int:
    new = _reload(_model_path(args)) if _model_path(args) else None
    if new is None:
        return 2
    if bool(args.against) == bool(args.against_build):
        print("give exactly one of --against OLD_MODEL_JSON or --against-build "
              "(an id from graph.db's build history, or `previous`)", file=sys.stderr)
        return 2
    try:
        if args.against:
            with open(args.against, encoding="utf-8") as f:
                old = from_dict(json.load(f))
        else:
            dbp = _db_path(args)
            if dbp is None:
                return 2
            conn = store.open_db(dbp)
            try:
                bid = None if args.against_build == "previous" else int(args.against_build)
                if bid is None:
                    rows = conn.execute("SELECT id FROM builds ORDER BY id DESC LIMIT 2").fetchall()
                    if len(rows) < 2:
                        print("graph.db holds only one build so far — build again after "
                              "the app changes", file=sys.stderr)
                        return 2
                    bid = rows[1][0]
                snap = store.load_build(conn, bid)
            finally:
                conn.close()
            if snap is None:
                print(f"no build #{bid} in graph.db", file=sys.stderr)
                return 2
            old = from_dict(snap)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
        what = f"--against {args.against}" if args.against else "the stored build"
        print(f"could not load {what}: {e}", file=sys.stderr)
        return 2
    d = diff_models(old, new)
    if args.json:
        print(json.dumps(d, indent=2))
        return 0
    print(f"{d['app']} — what changed  (+{d['totals']['appeared']} appeared, "
          f"-{d['totals']['gone']} gone)")
    print()
    if not d["areas"]:
        print("No drift between these two models.")
        return 0
    for a in d["areas"]:
        print(f"● {a['area']}")
        for x in a["appeared"]:
            ev = ", ".join(f"ev_{i}" for i in x.get("evidence", []))
            print(f"   + {x['kind']:<11} {x['label']}")
            print(f"       {x['why']}" + (f"  [{ev}]" if ev else ""))
        for x in a["gone"]:
            print(f"   - {x['kind']:<11} {x['label']}")
            print(f"       {x['why']}")
        print()
    print(d["note"])
    print(SOURCE)
    return 0


def cmd_falsify(args) -> int:
    path = _model_path(args)
    if path is None:
        return 2
    m = _reload(path)
    if m is None:
        return 2
    pkg = methodology_package(m, prompt=FALSIFY_PROMPT)
    out = ("\n".join(FALSIFY_PROMPT) + "\n\n"
           + "MODEL AND HYPOTHESES (JSON):\n```json\n"
           + json.dumps({"plan_scaffold": pkg["plan_scaffold"],
                         "model": pkg["model"]}, indent=2) + "\n```")
    if args.out_file:
        try:
            with atomic_write(args.out_file) as f:
                f.write(out)
        except OSError as e:
            print(f"could not write {args.out_file}: {e}", file=sys.stderr)
            return 2
        print(f"wrote {args.out_file}", file=sys.stderr)
    else:
        print(out)
    return 0


def cmd_animate(args) -> int:
    """Standalone animation from an existing model or a fresh build."""
    if args.log:
        _init_key()
        try:
            m = build(list(parse_items(args.log)), name=args.webapp)
        except (OSError, ValueError, SyntaxError) as e:
            print(f"could not read {args.log}: {e}", file=sys.stderr)
            return 2
    else:
        path = _model_path(args)
        if path is None:
            return 2
        m = _reload(path)
        if m is None:
            return 2
    if args.svg:
        try:
            write_svg(m, args.svg)
        except OSError as e:
            print(f"could not write {args.svg}: {e}", file=sys.stderr)
            return 2
        print(f"wrote {args.svg}")
    else:
        render_terminal(m, fast=args.no_type)
    return 0
