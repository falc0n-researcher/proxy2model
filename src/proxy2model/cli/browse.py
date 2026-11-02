"""`browse`: open a browser, record what you do in it, and keep the model up to date."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser

from ..core.domains import registrable_domain
from ..ingest import live as live_mod
from ..ingest.browse import Recorder
from ..ingest.browser import CDP, WebSocket, find_chrome, launch_chrome
from ..ingest.crawl import CrawlConfig, in_scope
from . import ui
from .build import _write_outputs
from .common import _clear_inputs, _init_key, _inputs_dir


def _ask(prompt: str, default: str = "") -> str:
    shown = f"  {prompt}" + (f" {ui.style('[' + default + ']', 'dim')}" if default else "") + ": "
    try:
        return input(shown).strip() or default
    except EOFError:
        return default


def _start_url(text: str) -> str:
    text = text.strip()
    return text if "://" in text else "https://" + text


_ROLE_RE = re.compile(r"[A-Za-z0-9._-]{1,40}")


def _bare(host: str) -> bool:
    """An IP address or a one-label name (localhost): no domain to widen the scope to."""
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return "." not in host


def _settings(args) -> bool:
    """Fill in the target, name, scope and mode, asking for what the command line left out.
    False when there is not enough to go on."""
    interactive = sys.stdin.isatty() and not args.yes
    if not args.url:
        if not interactive:
            print(ui.error("give the app's URL: proxy2model browse https://app.example.com"), file=sys.stderr)
            return False
        print()
        args.url = _ask("Web app URL", "")
        if not args.url:
            return False
    args.url = _start_url(args.url)
    host = (urllib.parse.urlsplit(args.url).hostname or "").lower()
    if not host:
        print(ui.error(f"not a URL: {args.url}"), file=sys.stderr)
        return False
    if not args.scope:
        default = host if _bare(host) else f"*.{registrable_domain(host) or host}"
        args.scope = [_ask("Scope, comma-separated (*.example.com is the domain and its subdomains)", default)
                      if interactive else default]
    if not args.webapp:
        default = "app" if _bare(host) else (registrable_domain(host) or host).split(".")[0]
        args.webapp = _ask("Name for the model", default) if interactive else default
    if args.active is None:
        args.active = (_ask("Mode: passive (only what you browse) or active (also crawl in a background tab)",
                            "passive").lower().startswith("a")) if interactive else False
    if args.active and not args.yes:
        if not interactive or not _ask("Active mode sends requests of its own (GET only, unless --allow-writes). "
                                       "Is this an app you are authorized to test? (yes/no)", "no").lower().startswith("y"):
            print(ui.error("active mode needs authorization: answer yes, or pass --yes"), file=sys.stderr)
            return False
    if args.role is None and interactive:
        args.role = _ask("Role for this session, e.g. anon, user, admin (Enter for none)", "") or None
    if args.role and not _ROLE_RE.fullmatch(args.role):
        print(ui.error("a role is letters, digits, '.', '_' or '-'"), file=sys.stderr)
        return False
    if args.keep_login is None:
        args.keep_login = interactive and _ask(
            "Keep this browser's login for the next session? It stays on disk outside the output (yes/no)",
            "no").lower().startswith("y")
    return True


def _profile_dir(webapp: str, role: str | None) -> str:
    """Where a kept login lives: real cookies, so outside any output folder, one per app and role."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "proxy2model", "profiles", webapp + (f"-{role}" if role else ""))


def _scope_list(values: list[str]) -> list[str]:
    out = []
    for v in values:
        for x in v.split(","):
            x = x.strip().lower()
            if x:
                x = x.split("://", 1)[-1].split("/", 1)[0]
                out.append(x)
    return out


def _open(ws_url: str, url: str) -> None:
    """Load the start page in the browser's first tab."""
    c = CDP(WebSocket(ws_url))
    try:
        pages = [t for t in c.call("Target.getTargets")["targetInfos"] if t["type"] == "page"]
        if pages:
            sid = c.call("Target.attachToTarget", {"targetId": pages[0]["targetId"], "flatten": True})["sessionId"]
            c.call("Page.navigate", {"url": url}, sid, 30)
        else:
            c.call("Target.createTarget", {"url": url})
    finally:
        c.ws.close()


def cmd_browse(args) -> int:
    if not _settings(args):
        return 2
    chrome = find_chrome(args.chrome)
    if not chrome:
        print(ui.error("no Chrome, Chromium, Edge or Brave found; install one or pass --chrome PATH"), file=sys.stderr)
        return 2
    scope = _scope_list(args.scope)
    args.scope = [s[2:] if s.startswith("*.") else s for s in scope]      # first-party, for the model
    start_host = (urllib.parse.urlsplit(args.url).hostname or "").lower()
    args.seed_host = start_host           # the site you opened is the app's main host, not the busiest one
    if not in_scope(args.url, scope):
        scope.append(start_host)

    _init_key()
    outdir = os.path.join(args.out, args.webapp)
    os.makedirs(outdir, exist_ok=True)
    if args.fresh:
        _clear_inputs(outdir)
    key = f"browse-{args.role}" if args.role else "browse"
    live = live_mod.Live(os.path.join(_inputs_dir(outdir), key + ".jsonl"), role=args.role)
    args.label = args.label or "browse"
    state = {"build": None}

    def rebuild() -> str:
        if _write_outputs(args, outdir, replace_build=state["build"], quiet=True) != 0:
            raise RuntimeError(f"could not write outputs to {outdir}")
        state["build"] = args._build_id
        args._model = None
        c = args._counts
        return "   ".join([ui.stat(c["hosts"], "host"), ui.stat(c["routes"], "route"),
                           ui.stat(c["endpoints"], "API")])

    def report(e: dict) -> None:
        stamp = ui.style(time.strftime("%H:%M:%S"), "dim")
        if "error" in e:
            print(f"  {stamp}  " + ui.error(f"rebuild failed: {e['error']}"), flush=True)
        elif "say" in e:
            print(f"  {stamp}  {e['say']}", flush=True)
        else:
            print(f"  {stamp}  {ui.style('+' + str(e['added']), 'green')}  {e['saved']} saved   {e['summary']}   "
                  + ui.style(f"{e['seconds']:.1f}s", "dim"), flush=True)

    if args.keep_login:
        tmp = _profile_dir(args.webapp, args.role)
        os.makedirs(tmp, mode=0o700, exist_ok=True)
    else:
        tmp = tempfile.mkdtemp(prefix="proxy2model-browser-")
    extra = ["--window-size=1366,900"] + (["--ignore-certificate-errors"] if args.insecure else [])
    try:
        proc, ws_url = launch_chrome(chrome, tmp, extra, headless=args.headless)
    except RuntimeError as e:
        if not args.keep_login:
            shutil.rmtree(tmp, ignore_errors=True)
        hint = " (is another browse session using this login?)" if args.keep_login else ""
        print(ui.error(f"could not start the browser: {e}{hint}"), file=sys.stderr)
        return 2

    recorder = Recorder(ws_url, lambda u: in_scope(u, scope), lambda items: live.ingest(items))
    worker = live_mod.Rebuilder(live, rebuild, args.interval, report)
    crawl = None
    try:
        recorder.start()
        recorder.ready.wait(15)
        worker.start()
        _open(ws_url, args.url)
        print("\n".join([
            "", ui.title("browse", args.webapp), "",
            ui.row("target", ui.style(args.url, "bold")),
            ui.row("scope", ", ".join(scope)),
            ui.row("mode", "active: crawling in a background tab while you browse" if args.active
                   else "passive: records only what you do"),
            ui.row("role", args.role or ui.style("none", "dim")),
            ui.row("login", f"kept in {tmp} (delete it to log out)" if args.keep_login
                   else "fresh browser profile, deleted when you finish"),
            ui.row("output", outdir.rstrip("/") + "/"),
            "", ui.style("  browse the app in the window that opened · close it or press Ctrl-C to finish", "dim"), "",
        ]), flush=True)
        if args.active:
            crawl = threading.Thread(target=_crawl, args=(args, chrome, ws_url, scope, report), daemon=True)
            crawl.start()
        while proc.poll() is None and recorder.is_alive():
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop.set()
        recorder.join(5)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not args.keep_login:
            shutil.rmtree(tmp, ignore_errors=True)
        worker.stop.set()
        worker.join(args.interval + 1)
    if recorder.error:
        print(ui.warn(f"recording stopped early: {recorder.error}"), file=sys.stderr)
    live.flush()
    if not live.saved:
        print(f"\n  nothing in scope was recorded ({', '.join(scope)})")
        return 1
    extras = [f"{recorder.assets_skipped} images, fonts and stylesheets and "
              f"{recorder.repeats_skipped} repeat script and preflight loads not recorded"]
    if recorder.frames:
        extras.append(f"{recorder.frames} WebSocket messages (handshakes recorded, messages not)")
    print(f"\n  done · {recorder.recorded} requests recorded this session, {live.saved} saved in all · "
          + " · ".join(extras))
    args._model = None
    rc = _write_outputs(args, outdir, replace_build=state["build"])
    if rc == 0:
        print(_visit_next(outdir, args.webapp))
        report_path = os.path.abspath(os.path.join(outdir, "report.html"))
        if args.open and sys.stdout.isatty() and os.path.exists(report_path):
            webbrowser.open("file://" + report_path)
    return rc


def _visit_next(outdir: str, webapp: str, limit: int = 12) -> str:
    """The endpoints the app's code names that this capture never reached: where to go next."""
    try:
        with open(os.path.join(outdir, "model.json"), encoding="utf-8") as f:
            nodes = json.load(f)["nodes"]
    except (OSError, ValueError, KeyError):
        return ""
    todo = sorted(n["label"] for n in nodes
                  if n["type"] == "endpoint" and n.get("attrs", {}).get("api_state") == "STATIC_ONLY")
    if not todo:
        return ""
    lines = ["", ui.row("visit next", f"{len(todo)} endpoints the app's code names that you have not reached yet")]
    lines += [" " * 12 + t for t in todo[:limit]]
    if len(todo) > limit:
        lines.append(" " * 12 + ui.style(f"+{len(todo) - limit} more: proxy2model query {webapp} reconcile", "dim"))
    return "\n".join(lines)


def _crawl(args, chrome: str, ws_url: str, scope: list[str], report) -> None:
    """Active mode: crawl in a background tab of the same browser, so it shares the login.
    Its traffic is recorded by the Recorder like any other tab's."""
    from ..ingest.browser import BrowserCrawler
    cfg = CrawlConfig(start=args.url, scope=scope, max_requests=args.max_requests, max_seconds=args.max_seconds,
                      read_only=not args.allow_writes, progress=False, insecure=args.insecure)
    report({"say": "active crawl started in a background tab"})
    try:
        res = BrowserCrawler(cfg, chrome, attach=ws_url).run()
        st = res.stats
        report({"say": f"active crawl done: {st['requests']} requests, {st['states']} page states, "
                       f"{st['clicks']} clicks"})
    except Exception as e:                       # the browser was closed mid-crawl, or a page broke it
        report({"say": ui.style(f"active crawl stopped: {e}", "dim")})
