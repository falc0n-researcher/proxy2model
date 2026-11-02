"""The argument parser and the entry point."""

from __future__ import annotations

import argparse
import os
import sys

from .. import __version__
from ..core.context import LENSES
from ..db import bql
from . import ui
from .history import cmd_builds, cmd_diff, cmd_watch
from .common import (
    _name,
)
from .build import (
    cmd_build, cmd_crawl,
)
from .analyze import (
    cmd_q, cmd_query, cmd_crossrole, cmd_osint, cmd_graph, cmd_methodology, cmd_gaps, cmd_changes, cmd_falsify, cmd_openapi, cmd_animate,
)
from .mcp import cmd_mcp
from .browse import cmd_browse


# What a researcher reaches for every day; everything else is one line under "More".
COMMANDS = [
    ("build", "build the model from a Burp XML, Logger++ CSV or HAR export"),
    ("browse", "open a browser, record what you do in it, build the model as you go"),
    ("crawl", "build the model by crawling a running app (authorized targets only)"),
    ("query", "ask the model a question, answered with evidence and no AI"),
    ("diff", "what changed between two builds"),
    ("openapi", "print the observed API as OpenAPI 3.0"),
]
MORE = ["cross-role", "builds", "watch", "q", "graph", "gaps", "changes", "mcp",
        "methodology", "falsify", "osint", "animate"]


def overview() -> str:
    """The top-level help: the everyday commands, then the rest on one line."""
    w = max(len(c) for c, _ in COMMANDS)
    out = [ui.title(__version__), "Captured proxy traffic in, an evidence-backed model of the web app out.", "",
           f"{ui.style('usage', 'dim')}  proxy2model <command> [options]",
           f"       proxy2model FILE ...     {ui.style('same as build FILE', 'dim')}", ""]
    out += [f"  {c.ljust(w)}   {d}" for c, d in COMMANDS]
    out += ["", f"  {ui.style('More:', 'dim')} {', '.join(MORE)}", "",
            ui.style("proxy2model <command> --help shows what a command does and its options.", "dim")]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="proxy2model",
        description="Turn captured proxy traffic (Burp, HAR, Logger++) into an evidence-backed web-app model.",
    )
    p.add_argument("--version", action="version", version=f"proxy2model {__version__}")
    p.set_defaults(func=None)
    subparsers = p.add_subparsers(dest="cmd", metavar="<command>")

    class _Sub:                             # every command's --help opens with what it does
        @staticmethod
        def add_parser(name, **kw):
            kw.setdefault("description", kw.get("help"))
            return subparsers.add_parser(name, **kw)
    sub = _Sub()

    b = sub.add_parser("build", help="build the model (also the default: `proxy2model file.xml`)")
    b.add_argument("log", help="Burp 'Save items' XML, Logger++ CSV or HAR export to build from")
    b.add_argument("--webapp", "-w", default="app", type=_name("--webapp"),
                   help="name for this app's model (default: app)")
    b.add_argument("--role", type=_name("--role"),
                   help="tag this capture with a role; role builds into the same "
                        "--out/--webapp are merged into one model")
    b.add_argument("--fresh", action="store_true",
                   help="discard previously merged role inputs first")
    b.add_argument("--scope", action="append",
                   help="first-party host or domain (repeatable or comma-separated); "
                        "default: the registrable domain of the busiest host")
    b.add_argument("--lens", choices=LENSES, default="attention",
                   help="ordering/filter for context.json")
    b.add_argument("--cap", type=int, default=40, metavar="N",
                   help="max items per section in context.json (default: 40)")
    b.add_argument("--out", default="proxy2model-out",
                   help="output directory (default: proxy2model-out)")
    b.add_argument("--screenshot", metavar="FILE",
                   help="a PNG, JPEG or WebP of the app to show on the report overview "
                        "(pixels are not masked: check it first)")
    b.add_argument("--label", metavar="TEXT",
                   help="a name for this build in the history (shown by `builds`, usable in `diff`)")
    b.add_argument("--osint", action="store_true",
                   help="also run light external recon on the primary host (off by default; "
                        "sends DNS/TLS/HTTP requests; PROXY2MODEL_OFFLINE=1 forces it off)")
    b.add_argument("--osint-timeout", type=float, default=5.0, metavar="SEC",
                   help="per-lookup timeout for the build's OSINT (default: 5)")
    b.add_argument("--skip-tools", metavar="TOOLS",
                   help="Logger++ CSV: drop rows from these Burp tools (comma-separated), e.g. Scanner")
    b.add_argument("--only-tools", metavar="TOOLS",
                   help="Logger++ CSV: keep only rows from these Burp tools, e.g. Proxy,Extensions")
    b.add_argument("--animate", action="store_true",
                   help="play the build animation in the terminal")
    b.add_argument("--no-type", action="store_true",
                   help="animation: skip the typing effect")
    b.set_defaults(func=cmd_build)

    cw = sub.add_parser("crawl", help="crawl a running web app and build the model from it, "
                                      "no proxy needed; authorized targets only")
    cw.add_argument("url", help="start URL, e.g. https://shop.example.com/")
    cw.add_argument("--yes", action="store_true", help="confirm you are authorized to test this target")
    cw.add_argument("--webapp", "-w", default="app", type=_name("--webapp"),
                    help="name for this app's model (default: app)")
    cw.add_argument("--role", type=_name("--role"),
                    help="tag this crawl with a role; crawls into the same --out/--webapp merge")
    cw.add_argument("--fresh", action="store_true", help="discard previously merged role inputs first")
    cw.add_argument("--scope", action="append",
                    help="extra in-scope hosts (host or host:port; repeatable or comma-separated). "
                         "The crawl never leaves the start origin plus these")
    cw.add_argument("--include-subdomains", action="store_true",
                    help="also crawl subdomains of the start host's registrable domain")
    cw.add_argument("--max-requests", type=int, default=3000, metavar="N",
                    help="request budget; 0 = no limit (default: 3000)")
    cw.add_argument("--max-assets", type=int, default=2000, metavar="N",
                    help="browser mode: cap on image/font/media loads (0 = no cap), so they don't "
                         "starve page and API budget on an asset-heavy site (default: 2000)")
    cw.add_argument("--depth", type=int, default=12, help="link depth from the start page (default: 12)")
    cw.add_argument("--max-seconds", type=float, default=0, metavar="SEC",
                    help="wall-clock limit for the whole crawl; 0 = none")
    cw.add_argument("--delay", type=float, default=0.1, metavar="SEC",
                    help="static mode: minimum seconds between requests (default: 0.1)")
    cw.add_argument("--threads", type=int, default=4, help="static mode: parallel fetches, 1-8 (default: 4)")
    cw.add_argument("--per-template-cap", type=int, default=25, metavar="N",
                    help="max variants of one path template, e.g. /item/{id} (default: 25)")
    cw.add_argument("--browser", choices=["auto", "on", "off"], default="auto",
                    help="crawl with a real Chrome/Chromium so JavaScript runs: auto (default) uses one "
                         "if installed, on requires it, off is the static crawler")
    cw.add_argument("--chrome", metavar="PATH", help="Chrome/Chromium binary (else found automatically, "
                                                      "or PROXY2MODEL_CHROME)")
    cw.add_argument("--max-clicks", type=int, default=25, metavar="N",
                    help="browser: clicks per page state (default: 25)")
    cw.add_argument("--no-interact", action="store_true", help="browser: load pages, do not click or fill")
    cw.add_argument("--no-forms", action="store_true", help="browser: fill fields but do not submit forms")
    cw.add_argument("--read-only", action="store_true",
                    help="browser: block every request that is not GET/HEAD/OPTIONS")
    cw.add_argument("--headful", action="store_true", help="browser: show the window (debugging)")
    cw.add_argument("--journey", action="append", metavar="FILE",
                    help="run a scripted journey (JSON: login, register, checkout, uploads …) before the "
                         "crawl, in the same session; repeatable. See the docs for the format")
    cw.add_argument("--var", action="append", metavar="name=value",
                    help="a variable for journeys, as ${name} (use ${env:NAME} for secrets)")
    cw.add_argument("--journey-only", action="store_true",
                    help="run the journeys and skip the autonomous crawl")
    cw.add_argument("--auth-storage", metavar="KEY",
                    help="browser: after --auth-login, store the token in localStorage[KEY] and cookie KEY "
                         "(what many SPAs read), e.g. token")
    cw.add_argument("--local-storage", action="append", metavar="key=value",
                    help="browser: set a localStorage value before the app loads (repeatable)")
    cw.add_argument("--timeout", type=float, default=10.0, help="per-request timeout in seconds")
    cw.add_argument("--header", action="append", metavar="'Name: value'",
                    help="extra request header, e.g. 'Authorization: Bearer ...' (repeatable)")
    cw.add_argument("--cookie", metavar="'a=b; c=d'", help="initial cookies, to crawl as a logged-in user")
    cw.add_argument("--auth-login", metavar="URL",
                    help="POST credentials here first and carry the token (see --auth-body, --auth-token)")
    cw.add_argument("--auth-body", metavar="JSON|@FILE", help="JSON body for --auth-login")
    cw.add_argument("--auth-token", metavar="PATH",
                    help="dotted path to the token in the login reply, e.g. authentication.token")
    cw.add_argument("--auth-scheme", default="Bearer", help="Authorization scheme for the token (default: Bearer)")
    cw.add_argument("--no-probe-js", action="store_true",
                    help="do not request the GET endpoints that scripts and pages name")
    cw.add_argument("--submit-forms", action="store_true",
                    help="also POST forms with benign sample values (never forms with a password field)")
    cw.add_argument("--respect-robots", action="store_true", help="skip paths robots.txt disallows")
    cw.add_argument("--insecure", action="store_true", help="do not verify TLS certificates")
    cw.add_argument("--save-xml", metavar="PATH",
                    help="also write the crawl as a Burp 'Save items' XML (contains raw values)")
    cw.add_argument("--lens", choices=LENSES, default="attention", help="ordering/filter for context.json")
    cw.add_argument("--cap", type=int, default=40, metavar="N", help="max items per section in context.json")
    cw.add_argument("--out", default="proxy2model-out", help="output directory (default: proxy2model-out)")
    cw.add_argument("--animate", action="store_true", help="play the build animation in the terminal")
    cw.add_argument("--no-type", action="store_true", help="animation: skip the typing effect")
    cw.add_argument("--screenshot", metavar="FILE",
                   help="a PNG, JPEG or WebP of the app to show on the report overview "
                        "(pixels are not masked: check it first)")
    cw.add_argument("--label", metavar="TEXT",
                   help="a name for this build in the history (shown by `builds`, usable in `diff`)")
    cw.add_argument("--no-screenshot", action="store_true",
                    help="do not capture the start page (an anonymous browser crawl does by default)")
    cw.add_argument("--osint", action="store_true",
                    help="also run light external recon on the primary host (off by default)")
    cw.add_argument("--osint-timeout", type=float, default=5.0, metavar="SEC")
    cw.set_defaults(func=cmd_crawl)

    q = sub.add_parser("query", help="ask the model a factual question (no AI); try 'help'")
    q.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    q.add_argument("question", help="the question; `help` lists what can be asked")
    q.add_argument("--out", default="proxy2model-out",
                   help="output directory used at build time")
    q.set_defaults(func=cmd_query)

    bq = sub.add_parser("q", help="query graph.db with BQL (HTTPQL-style filters + graph "
                                  "verbs); no query opens an interactive prompt")
    bq.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    bq.add_argument("query", nargs="*", help="a BQL query; `help` prints the language")
    bq.add_argument("--format", choices=["table", "json"], default="table")
    bq.add_argument("--limit", type=int, default=bql.DEFAULT_LIMIT, help="max rows (default: 100)")
    bq.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    bq.set_defaults(func=cmd_q)

    cr = sub.add_parser("cross-role", help="compare what two roles reached")
    cr.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    cr.add_argument("--low", required=True, type=_name("--low"),
                    help="the less-privileged role (as tagged with --role)")
    cr.add_argument("--high", required=True, type=_name("--high"),
                    help="the more-privileged role (as tagged with --role)")
    cr.add_argument("--json", action="store_true", help="print JSON instead of text")
    cr.add_argument("--out", default="proxy2model-out",
                    help="output directory used at build time")
    cr.set_defaults(func=cmd_crossrole)

    o = sub.add_parser("osint", help="external recon for a host (DNS, TLS, headers, tech, "
                                     "email, subdomains, RDAP); authorized targets only")
    o.add_argument("host")
    o.add_argument("--webapp", "-w", type=_name("--webapp"),
                   help="save osint.json into OUT/WEBAPP/ so build folds it into context.json")
    o.add_argument("--yes", action="store_true", help="confirm you are authorized to test this host")
    o.add_argument("--ports", action="store_true", help="also TCP-connect common ports")
    o.add_argument("--no-subdomains", action="store_true", help="skip certificate-transparency lookup")
    o.add_argument("--timeout", type=float, default=6.0,
                   help="per-lookup timeout in seconds (default: 6)")
    o.add_argument("--out", default="proxy2model-out",
                   help="output directory (default: proxy2model-out)")
    o.add_argument("--json", action="store_true", help="print JSON instead of the text summary")
    o.add_argument("--out-file", help="write the JSON report to this path")
    o.set_defaults(func=cmd_osint)

    g = sub.add_parser("graph", help="reason over the graph, or export it "
                                     "(GraphML / Cypher / JSON) for tooling and AI")
    g.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    g.add_argument("--format", choices=["overview", "reason", "json", "graphml", "cypher"],
                   default="overview",
                   help="overview (text), reason (graph+reasoning JSON for an LLM), "
                        "json (node-link), graphml (Gephi/yEd), cypher (Neo4j)")
    g.add_argument("--reach", metavar="NODE",
                   help="show how a node is reached (entry-point paths)")
    g.add_argument("--blast", metavar="NODE",
                   help="show what a node touches downstream")
    g.add_argument("--touched-by", metavar="NODE",
                   help="show what leads into a node upstream")
    g.add_argument("--depth", type=int, default=3, help="hops for --blast/--touched-by")
    g.add_argument("--out-file", help="write the output to this path")
    g.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    g.set_defaults(func=cmd_graph)

    gp = sub.add_parser("gaps", help="rank the model's open questions by how much "
                                     "resolving each improves the picture")
    gp.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    gp.add_argument("--json", action="store_true", help="print JSON")
    gp.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    gp.set_defaults(func=cmd_gaps)

    bw = sub.add_parser("browse", help="open a browser and build the model from what you do in it; "
                                       "asks for the URL, scope and mode when they are not given")
    bw.add_argument("url", nargs="?", help="the app's start URL")
    bw.add_argument("--webapp", "-w", type=_name("--webapp"),
                    help="name for this app's model (default: from the domain)")
    bw.add_argument("--scope", action="append",
                    help="what to record: host, host:port or *.domain (repeatable or comma-separated; "
                         "default: *.<the URL's domain>)")
    mode = bw.add_mutually_exclusive_group()
    mode.add_argument("--active", dest="active", action="store_true", default=None,
                      help="also crawl the app in a background tab, sharing your login (authorized targets only)")
    mode.add_argument("--passive", dest="active", action="store_false",
                      help="record only what you do (the default)")
    bw.add_argument("--yes", action="store_true",
                    help="ask nothing: you are authorized to test the target; defaults fill the rest")
    bw.add_argument("--role", type=_name("--role"), help="tag this session's traffic with a role")
    bw.add_argument("--fresh", action="store_true",
                    help="discard every saved input (earlier builds and sessions) first")
    bw.add_argument("--allow-writes", action="store_true",
                    help="active crawl: also let through the POST/PUT/DELETE the app itself sends "
                         "(by default the crawl tab sends GET only, since it shares your login)")
    bw.add_argument("--keep-login", dest="keep_login", action="store_true", default=None,
                    help="keep the browser profile (and its login) for the next session; it holds real "
                         "cookies and lives in ~/.config/proxy2model/profiles/, outside the output")
    bw.add_argument("--no-open", dest="open", action="store_false", help="do not open the report when done")
    bw.add_argument("--max-requests", type=int, default=3000, metavar="N",
                    help="active crawl: stop after N requests (default: 3000; 0 = no limit)")
    bw.add_argument("--max-seconds", type=float, default=0, metavar="SEC", help="active crawl: time limit")
    bw.add_argument("--chrome", metavar="PATH", help="the Chrome/Chromium/Edge/Brave to use (default: found)")
    bw.add_argument("--insecure", action="store_true", help="accept invalid TLS certificates")
    bw.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)       # tests
    bw.add_argument("--interval", type=float, default=5.0, metavar="SEC",
                    help="rebuild at most this often while new traffic arrives (default: 5)")
    bw.add_argument("--lens", choices=LENSES, default="attention", help="ordering/filter for context.json")
    bw.add_argument("--cap", type=int, default=40, metavar="N", help="max items per section in context.json")
    bw.add_argument("--label", metavar="TEXT", help="name for this session's build in the history (default: browse)")
    bw.add_argument("--out", default="proxy2model-out", help="output directory (default: proxy2model-out)")
    bw.set_defaults(func=cmd_browse)

    mc = sub.add_parser("mcp", help="serve the built models to an AI agent over MCP (stdio); read-only")
    mc.add_argument("--out", default="proxy2model-out",
                    help="output directory holding the models (default: proxy2model-out); give an absolute path")
    mc.set_defaults(func=cmd_mcp)

    oa = sub.add_parser("openapi", help="export the observed API as an OpenAPI 3.0 document")
    oa.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    oa.add_argument("-o", "--output", metavar="FILE", help="write here instead of stdout")
    oa.add_argument("--host", help="only endpoints on this host")
    oa.add_argument("--include-static", action="store_true",
                    help="also include endpoints the client code references but the capture never reached")
    oa.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    oa.set_defaults(func=cmd_openapi)

    ch = sub.add_parser("changes", help="diff this model against an older one, "
                                        "grouped by feature area (drift, never findings)")
    ch.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    ch.add_argument("--against", metavar="OLD_MODEL_JSON",
                    help="path to an earlier model.json to compare against")
    ch.add_argument("--against-build", metavar="ID|previous",
                    help="compare against a build stored in graph.db (see `q shop "
                         "\"sql SELECT id, built_at FROM builds\"`), or `previous`")
    ch.add_argument("--json", action="store_true", help="print JSON")
    ch.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    ch.set_defaults(func=cmd_changes)

    df = sub.add_parser("diff", help="what changed between two builds of an app: new workflows, "
                                     "changed fingerprints, gone things (drift, never findings)")
    df.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    df.add_argument("a", nargs="?", metavar="FROM",
                    help="the older build: an id, `previous`, `first` or a label (default: previous)")
    df.add_argument("b", nargs="?", metavar="TO",
                    help="the newer build (default: latest)")
    df.add_argument("--json", action="store_true", help="print JSON")
    df.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    df.set_defaults(func=cmd_diff)

    wa = sub.add_parser("watch", help="watch a folder of exports: each new export becomes a build, "
                                      "and the change from the last one is printed")
    wa.add_argument("folder", help="folder exports (Burp Save items XML, Logger++ CSV or HAR) are saved into")
    wa.add_argument("--webapp", "-w", required=True, type=_name("webapp"), help="name for the model")
    wa.add_argument("--interval", type=float, default=5.0, metavar="SEC", help="seconds between checks (default: 5)")
    wa.add_argument("--once", action="store_true", help="process what is there and exit instead of watching")
    wa.add_argument("--skip-existing", action="store_true",
                    help="only react to exports that appear after this starts")
    wa.add_argument("--pattern", default="*.xml,*.csv,*.har", help="file patterns to pick up (default: *.xml,*.csv,*.har)")
    wa.add_argument("--role", help="tag each export with this role (merges with other roles' inputs)")
    wa.add_argument("--scope", action="append", help="in-scope host (repeatable), as for build")
    wa.add_argument("--skip-tools", metavar="TOOLS", help="Logger++ CSV: drop rows from these Burp tools")
    wa.add_argument("--osint", action="store_true", help="also run light external recon on each build")
    wa.add_argument("--out", default="proxy2model-out", help="output directory (default: proxy2model-out)")
    wa.set_defaults(func=cmd_watch)

    bl = sub.add_parser("builds", help="list the builds kept in graph.db, to pick two to diff")
    bl.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    bl.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    bl.set_defaults(func=cmd_builds)

    fa = sub.add_parser("falsify", help="emit an AI prompt that stress-tests the "
                                        "scaffold's hypotheses (tries to eliminate them)")
    fa.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    fa.add_argument("--out-file", help="write the prompt to this path")
    fa.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    fa.set_defaults(func=cmd_falsify)

    me = sub.add_parser("methodology", help="a target-specific recon & hunting "
                                           "scaffold, or the AI prompt that turns it "
                                           "into a methodology (no generic checklist)")
    me.add_argument("webapp", type=_name("webapp"), help="model name used at build time")
    me.add_argument("--prompt", action="store_true",
                    help="emit the full AI-ready prompt + model to paste into a chat model")
    me.add_argument("--json", action="store_true", help="the scaffold as JSON")
    me.add_argument("--out-file", help="write the output to this path")
    me.add_argument("--out", default="proxy2model-out", help="output directory used at build time")
    me.set_defaults(func=cmd_methodology)

    an = sub.add_parser("animate", help="render the build animation (terminal or --svg)")
    an.add_argument("--webapp", "-w", default="app", type=_name("--webapp"),
                    help="model name used at build time")
    an.add_argument("--log", help="build fresh from this export instead of a saved model")
    an.add_argument("--svg", help="write an animated SVG to this path")
    an.add_argument("--out", default="proxy2model-out",
                    help="output directory used at build time")
    an.add_argument("--no-type", action="store_true", help="skip the typing effect")
    an.set_defaults(func=cmd_animate)

    argv = list(sys.argv[1:] if argv is None else argv)
    known = {"build", "crawl", "query", "q", "cross-role", "osint", "graph", "methodology",
             "gaps", "openapi", "browse", "mcp", "changes", "diff", "builds", "watch", "falsify", "animate", "-h", "--help", "--version"}
    # bare `proxy2model file.xml ...` → treat as build, but only when the first
    # word is a real file; a typo'd subcommand gets a clear error instead
    if argv and argv[0] not in known and not argv[0].startswith("-"):
        if not os.path.exists(argv[0]):
            print(ui.error(f"{argv[0]!r} is not a command or an existing file."), file=sys.stderr)
            print("run `proxy2model` to list the commands", file=sys.stderr)
            return 2
        argv = ["build"] + argv

    if not argv or argv[0] in ("-h", "--help"):
        print(overview())
        return 0 if argv else 1
    args = p.parse_args(argv)

    if getattr(args, "func", None) is None:
        print(overview())
        return 1
    return args.func(args)
