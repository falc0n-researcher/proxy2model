"""`build` and `crawl`: parse, save the input, build the model, write every output."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

from ..report import shot
from ..atomic import atomic_write
from ..ingest.parse import parse_items
from ..core.model import build, dump_model
from ..core.context import context_package
from ..report.animate import render_terminal, write_svg
from ..report.html import write_html_report
from ..core.graph import (
    to_graphml, to_graph_json,
)
from ..db import store
from ..export.openapi import to_openapi
from . import ui
from .history import _changes_since_previous
from .common import (
    EXPORTS,
    DEFAULT_INPUT, _init_key, _inputs_dir, _save_input, _stage_input, _drop_if_empty, _clear_inputs, _load_inputs, _scope,
)


def cmd_build(args) -> int:
    _init_key()
    stats: dict = {}
    outdir = os.path.join(args.out, args.webapp)
    os.makedirs(outdir, exist_ok=True)
    staged = None
    try:
        staged, count = _stage_input(outdir, parse_items(
            args.log, role=args.role, stats=stats,
            skip_tools=tuple((args.skip_tools or "").split(",")),
            only_tools=tuple((args.only_tools or "").split(","))), stats)
    except (OSError, ValueError, SyntaxError) as e:
        _drop_if_empty(outdir)
        if str(args.log).lower().endswith(".har"):
            extra = "\nExpected a HAR file: browser DevTools (Save all as HAR), Hetty, mitmproxy, ZAP or Charles can export one."
        elif str(args.log).lower().endswith(".csv"):
            extra = ("\nExpected a Burp Logger++ CSV export with Method, Host, Request and Response "
                     "columns (Request/Response base64 or raw HTTP).")
        elif isinstance(e, SyntaxError):
            extra = ("\nThis does not look like a Burp 'Save items' export.\n"
                     "In Burp: Proxy → HTTP history → select all → right-click → "
                     "Save items → history.xml (keep base64 encoding on).")
        else:
            extra = ""
        print(f"could not read {args.log}: {e}{extra}", file=sys.stderr)
        return 2
    if stats.get("tools"):
        mix = ", ".join(f"{t} {n}" for t, n in sorted(stats["tools"].items(), key=lambda kv: -kv[1]))
        print(f"logger csv: {mix}" + (f" · skipped {stats['filtered']} by tool" if stats.get("filtered") else ""),
              file=sys.stderr)
        if "Scanner" in stats["tools"] and not stats.get("filtered") and stats["tools"]["Scanner"] >= 20:
            print("  note: this export includes Scanner traffic (active-scan probes). They show up as "
                  "endpoints in the model; add --skip-tools Scanner to model the app without them.",
                  file=sys.stderr)
    if not count:
        os.remove(staged)
        _drop_if_empty(outdir)
        if stats.get("items", 0) == 0:
            print(f"{args.log}: no requests found. This does not look like a Burp "
                  "'Save items' export, a Logger++ CSV or a HAR file.\n"
                  "In Burp: Proxy → HTTP history → select all → right-click → "
                  "Save items → history.xml (keep base64 encoding on).", file=sys.stderr)
        else:
            print(f"{args.log}: found {stats['items']} item(s) but none could be parsed. "
                  "Check the export is a full Burp 'Save items' XML with base64-encoded "
                  "requests and responses.", file=sys.stderr)
        return 2
    return _build_from(args, [], stats, staged=staged)


def _build_from(args, exchanges: list, stats: dict, staged: str | None = None) -> int:
    """Everything after parsing: save inputs, merge roles, build, write every output."""
    outdir = os.path.join(args.out, args.webapp)
    os.makedirs(outdir, exist_ok=True)

    # A role build adds to (or replaces) that role's input; anything else starts over. The new input
    # is in place before the old ones go, so a crash in between never leaves the folder with neither.
    key = args.role or DEFAULT_INPUT
    if staged:
        os.replace(staged, os.path.join(_inputs_dir(outdir), key + ".jsonl"))
    else:
        _save_input(outdir, key, exchanges, stats)
    if args.role is None or args.fresh:
        _clear_inputs(outdir, keep=key)
    else:
        _clear_inputs(outdir, only=DEFAULT_INPUT, keep=key)
    exchanges.clear()                   # the saved input is the source from here; free the copy
    return _write_outputs(args, outdir)


def _write_outputs(args, outdir: str, replace_build: int | None = None, quiet: bool = False) -> int:
    """Build the model from every saved input and write every output. `browse` calls this on each
    rebuild with `quiet` and the build to overwrite; the build id and counts are left on `args`."""
    all_ex, all_stats, merged = _load_inputs(outdir)

    m = build(all_ex, name=args.webapp, scope=_scope(args), stats=all_stats)
    all_ex.clear()                      # the model holds what it needs; keeps peak memory down
    if m.counts()["hosts"] == 0 and not quiet:
        print(ui.warn(f"no captured host matched the scope ({', '.join(m.scope) or 'none'}); every "
                      "request was treated as third-party. Check --scope."), file=sys.stderr)
    osint_path = os.path.join(outdir, "osint.json")
    osint_data = _collect_osint(args, m, osint_path)
    try:
        picture = _pick_screenshot(args, outdir)
    except (OSError, ValueError) as e:
        print(f"could not use the screenshot: {e}", file=sys.stderr)
        return 2

    try:
        with atomic_write(os.path.join(outdir, "model.json")) as f:
            f.writelines(dump_model(m, indent=2))
        db_path = os.path.join(outdir, store.DB_NAME)
        dbs = store.write_db(m, db_path, osint=osint_data, label=getattr(args, "label", None),
                             replace_build=replace_build)
        args._build_id, args._counts = dbs.get("build"), m.counts()
        if dbs.get("damaged"):
            print(ui.warn(f"{db_path} was damaged; kept it aside as {dbs['damaged']} and started a "
                          "new graph.db (earlier builds are in the kept file)"), file=sys.stderr)
        write_html_report(m, os.path.join(outdir, "report.html"),
                          osint=osint_data, lens=args.lens, db_path=db_path, screenshot=picture,
                          changes=_changes_since_previous(db_path, dbs.get("build")))
        if picture:
            with atomic_write(os.path.join(outdir, shot.filename(picture[0])), "wb") as f:
                f.write(picture[1])
        with atomic_write(os.path.join(outdir, "context.json")) as f:
            # compact: this file is pasted into an AI, where indentation is tokens
            json.dump(context_package(m, lens=args.lens, cap=args.cap,
                                      osint=osint_data), f, separators=(",", ":"))
        with atomic_write(os.path.join(outdir, "openapi.json")) as f:
            json.dump(to_openapi(m), f, indent=2)
        exports = os.path.join(outdir, EXPORTS)
        os.makedirs(exports, exist_ok=True)
        write_svg(m, os.path.join(exports, "build.svg"))
        with atomic_write(os.path.join(exports, "graph.json")) as f:
            json.dump(to_graph_json(m), f, indent=2)
        with atomic_write(os.path.join(exports, "graph.graphml")) as f:
            f.write(to_graphml(m))
        for old in ("build.svg", "graph.json", "graph.graphml"):     # where versions before 2.0 put them
            if os.path.isfile(os.path.join(outdir, old)):
                os.remove(os.path.join(outdir, old))
    except (OSError, ValueError, sqlite3.Error) as e:
        print(f"could not write outputs to {outdir}: {e}", file=sys.stderr)
        return 2

    if quiet:
        args._model = m
        return 0
    if getattr(args, "animate", False):
        render_terminal(m, fast=args.no_type)
    print(_summary(args, outdir, m, all_stats, merged))
    return 0


def _summary(args, outdir: str, m, stats: dict, merged: list[str]) -> str:
    """What the build read, what the model holds, where everything went, and what to run next."""
    c = m.counts()
    st = c["api_state"]
    source = getattr(args, "log", None) or getattr(args, "url", None) or "saved inputs"
    # input names are roles, except the untagged ones; browser sessions save as browse[-ROLE]
    roles = sorted({n.split("-", 1)[1] if n.startswith(("browse-", "live-")) else n for n in merged}
                   - {DEFAULT_INPUT, "browse", "live"})
    lines = ["", ui.title("build", args.webapp), "",
             ui.row("input", str(source))]
    if roles:
        lines.append(ui.row("roles", ", ".join(roles) + ui.style("  (merged into one model)", "dim")))
    if stats.get("skipped"):
        lines.append(ui.row("skipped", f"{stats['skipped']} unparseable items"))
    lines += [
        ui.row("scope", ", ".join(m.scope) or "none"),
        "",
        ui.row("model", "   ".join([ui.stat(stats.get("parsed", 0), "request"), ui.stat(c["hosts"], "host"), ui.stat(c["routes"], "route"),
                                    ui.stat(c["endpoints"], "API"), ui.stat(c["parameters"], "param"),
                                    ui.stat(c["unknowns"], "unknown")])),
        ui.row("APIs", f"{st.get('RUNTIME_ONLY', 0)} seen in traffic only · "
                       f"{st.get('STATIC_ONLY', 0)} in code only · {st.get('BOTH', 0)} both"),
        "",
        ui.row("output", ui.style(outdir.rstrip("/") + "/", "bold") + "\n" + ui.files([
            ("report.html", "open in a browser"),
            ("model.json", "the model and the request behind every claim"),
            ("openapi.json", "the observed API, OpenAPI 3.0"),
            ("context.json", "what to hand an AI instead of raw traffic"),
            ("graph.db", "the model as a SQLite graph"),
            (EXPORTS + "/", "graph.json · graph.graphml · build.svg"),
        ])),
        "",
        ui.row("next", f"proxy2model query {args.webapp} help"),
    ]
    return "\n".join(lines)


def _pick_screenshot(args, outdir: str):
    """A picture for the overview: the one given, else the crawl's, else one saved by an earlier build."""
    if getattr(args, "screenshot", None):
        return shot.load(args.screenshot)
    return getattr(args, "_shot", None) or shot.existing(outdir)


def _primary_host(m) -> str | None:
    """The first-party host with the most evidence — the one worth probing."""
    hosts = [n for n in m.nodes.values() if n.type == "host"]
    if not hosts:
        return None
    return max(sorted(hosts, key=lambda n: n.label), key=lambda n: len(n.evidence)).label


def _probe_host(host: str | None) -> str | None:
    """A hostname OSINT can meaningfully look up, or None."""
    if not host:
        return None
    host = host.lower().split(":")[0]
    if (not re.match(r"^[a-z0-9.\-]{1,253}$", host) or "." not in host
            or re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host)
            or host.endswith((".local", ".localhost", ".internal", ".test", ".invalid",
                              ".example", ".lan", ".corp", ".home"))
            or host in ("example.com", "example.net", "example.org")
            or host.endswith((".example.com", ".example.net", ".example.org"))):
        return None
    return host


def _collect_osint(args, m, osint_path: str) -> dict | None:
    """External recon runs only with --osint and never fails a build.

    Live results replace the stored osint.json; if the lookup is skipped or
    fails, the last saved run is reused so the graph keeps its recon layer.
    """
    saved = None
    if os.path.exists(osint_path):
        try:
            with open(osint_path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = None
    if not getattr(args, "osint", False) or os.environ.get("PROXY2MODEL_OFFLINE") == "1":
        return saved
    host = _probe_host(_primary_host(m))
    if host is None:
        print("osint: skipped (no public hostname among first-party hosts)", file=sys.stderr)
        return saved
    from ..recon import osint as osint_mod
    print(f"osint: probing {host} — DNS, TLS, headers, CT logs, RDAP "
          f"(PROXY2MODEL_OFFLINE=1 forces offline)", file=sys.stderr)
    try:
        result = osint_mod.run(host, timeout=args.osint_timeout, want_ports=False,
                               want_subdomains=True).to_dict()
        with atomic_write(osint_path) as f:
            json.dump(result, f, indent=2)
        return result
    except Exception as e:                                   # fail soft: recon is optional
        print(f"osint: failed ({e}); continuing without fresh recon", file=sys.stderr)
        return saved


def _wants_screenshot(args, headers, cookies, journeys, local_storage) -> bool:
    """Only a signed-out start page is captured on its own; a signed-in page may show someone's data."""
    return not (args.no_screenshot or args.screenshot or args.auth_login or cookies or journeys
                or local_storage or args.auth_storage
                or any(k.lower() in ("authorization", "cookie") for k in headers))


def cmd_crawl(args) -> int:
    from ..ingest import crawl as crawl_mod
    from ..ingest.parse import parse_elements
    _init_key()
    if not (args.yes or os.environ.get("PROXY2MODEL_CRAWL_CONSENT") == "1"):
        print(
            "crawl sends live requests to the target (GET only unless --submit-forms).\n"
            "Only crawl applications you are authorized to test.\n"
            f"  target: {args.url}\n"
            "Re-run with --yes to confirm you have authorization.", file=sys.stderr)
        return 2
    headers = {}
    for h in args.header or []:
        k, sep, v = h.partition(":")
        if not sep or not k.strip():
            print(f"--header must look like 'Name: value' (got {h!r})", file=sys.stderr)
            return 2
        headers[k.strip()] = v.strip()
    cookies = {}
    for c in (args.cookie or "").split(";"):
        k, sep, v = c.strip().partition("=")
        if sep and k:
            cookies[k] = v
    auth_body = args.auth_body
    if auth_body and auth_body.startswith("@"):
        try:
            with open(auth_body[1:], encoding="utf-8") as f:
                auth_body = f.read()
        except OSError as e:
            print(f"could not read {auth_body[1:]}: {e}", file=sys.stderr)
            return 2
    if args.auth_login and not auth_body:
        print("--auth-login needs --auth-body (JSON, or @file)", file=sys.stderr)
        return 2
    scope = [x.strip() for v in (args.scope or []) for x in v.split(",") if x.strip()]
    from ..ingest import journey as jy
    journeys = []
    for path in args.journey or []:
        try:
            journeys.append(jy.load(path))
        except jy.JourneyError as e:
            print(f"journey: {e}", file=sys.stderr)
            return 2
    journey_vars = {}
    for kv in args.var or []:
        k, sep, v = kv.partition("=")
        if not sep or not k:
            print(f"--var must look like name=value (got {kv!r})", file=sys.stderr)
            return 2
        journey_vars[k] = v
    if args.journey_only and not journeys:
        print("--journey-only needs at least one --journey FILE", file=sys.stderr)
        return 2
    local_storage = {}
    for kv in args.local_storage or []:
        k, sep, v = kv.partition("=")
        if not sep or not k:
            print(f"--local-storage must look like key=value (got {kv!r})", file=sys.stderr)
            return 2
        local_storage[k] = v
    try:
        cfg = crawl_mod.CrawlConfig(
            start=args.url, scope=scope, include_subdomains=args.include_subdomains,
            max_requests=args.max_requests, max_depth=args.depth, delay=args.delay,
            timeout=args.timeout, threads=args.threads, headers=headers, cookies=cookies,
            probe_js=not args.no_probe_js, submit_forms=args.submit_forms,
            respect_robots=args.respect_robots, insecure=args.insecure,
            auth_login=args.auth_login, auth_body=auth_body, auth_token=args.auth_token,
            auth_scheme=args.auth_scheme, max_seconds=args.max_seconds, browser=args.browser,
            chrome=args.chrome, max_clicks=args.max_clicks, no_interact=args.no_interact,
            no_forms=args.no_forms, read_only=args.read_only, headful=args.headful,
            auth_storage=args.auth_storage, local_storage=local_storage,
            per_template_cap=args.per_template_cap, journeys=journeys, journey_vars=journey_vars,
            journey_only=args.journey_only, max_assets=args.max_assets,
            screenshot=_wants_screenshot(args, headers, cookies, journeys, local_storage))
        crawler = crawl_mod.make_crawler(cfg)
    except ValueError as e:
        print(f"crawl: {e}", file=sys.stderr)
        return 2
    browser_mode = bool(getattr(crawler, "chrome", None))
    mode = ("a real browser (JavaScript on; clicks and benign form fills; "
            + ("read-only" if cfg.read_only else "in-scope POST/PUT/DELETE the app itself makes are allowed")
            + ")") if browser_mode else ("static: GET only" if not cfg.submit_forms
                                           else "static: GET + benign form posts")
    print(f"crawl: {args.url}  scope: {', '.join(crawler.scope)}  mode: {mode}  "
          f"(budget {cfg.max_requests or 'unlimited'} requests, depth {cfg.max_depth})", file=sys.stderr)
    try:
        res = crawler.run()
    except KeyboardInterrupt:
        print("crawl: interrupted; building from what was fetched", file=sys.stderr)
        res = crawl_mod.CrawlResult(crawler.items, crawler.stats, crawler.forms, crawler.scope)
    st = res.stats
    print(f"crawl: {st['requests']} requests ({st['pages']} pages, {st['assets']} assets, "
          f"{st['js_probes']} API/code calls) · {st['forms_found']} forms · "
          f"skipped: {st['skipped_out_of_scope']} out of scope, {st['skipped_unsafe']} unsafe-looking, "
          f"{st['skipped_duplicate']} duplicate, {st['skipped_cap']} over a cap · "
          f"{st['errors']} errors", file=sys.stderr)
    if journeys:
        print(f"crawl: journeys — {st['journey_steps'] - st['journey_failed']} of {st['journey_steps']} "
              f"steps ran cleanly", file=sys.stderr)
    if st.get("browser"):
        print(f"crawl: browser — {st['states']} page states, {st['clicks']} clicks, "
              f"{st['forms_submitted']} forms submitted, blocked before sending: "
              f"{st['blocked_scope']} out of scope, {st['blocked_unsafe']} unsafe-looking, "
              f"{st['blocked_method']} non-GET (read-only), {st.get('blocked_asset_cap', 0)} over the asset cap, "
              f"{st['dialogs_dismissed']} dialogs dismissed",
              file=sys.stderr)
    if st["js_refs_not_requested"]:
        print(f"crawl: {st['js_refs_not_requested']} code reference(s) name a non-GET method "
              "and were not sent", file=sys.stderr)
    if args.save_xml:
        try:
            with atomic_write(args.save_xml) as f:
                f.write(crawl_mod.to_burp_xml(res.items))
            print(f"wrote {args.save_xml} (Burp 'Save items' format; holds raw values, "
                  "unlike every proxy2model output)", file=sys.stderr)
        except OSError as e:
            print(f"could not write {args.save_xml}: {e}", file=sys.stderr)
    args._shot = ("image/jpeg", res.screenshot) if getattr(res, "screenshot", None) else None
    pstats: dict = {}
    exchanges = list(parse_elements(res.items, source="crawl", role=args.role, stats=pstats))
    if not exchanges:
        print("crawl: nothing was fetched — is the target reachable?", file=sys.stderr)
        return 2
    return _build_from(args, exchanges, pstats)
