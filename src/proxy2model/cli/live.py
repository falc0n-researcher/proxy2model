"""`serve`: keep a model up to date from traffic a proxy pushes."""

from __future__ import annotations

import os
import sys
import time

from ..ingest import serve as live_serve
from . import ui
from .common import (
    _init_key, _inputs_dir, _clear_inputs,
)
from .build import (
    _write_outputs,
)


def caido_script(url: str, token: str | None) -> str:
    """The Caido passive-workflow script, pointed at this listener."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "caido-workflow.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    return js.replace("__INGEST_URL__", url).replace("__TOKEN__", token or "")


def cmd_serve(args) -> int:
    loopback = args.bind in live_serve.LOOPBACK
    token = args.token or os.environ.get("PROXY2MODEL_TOKEN") or None
    host_part = f"[{args.bind}]" if ":" in args.bind else args.bind
    url = f"http://{host_part if loopback else '127.0.0.1'}:{args.port}{live_serve.INGEST_PATH}"
    if args.caido_script:
        print(caido_script(url, token), end="")
        return 0
    if not loopback and not token:
        print(ui.error(f"binding {args.bind} exposes the listener to the network; "
                       "set --token (or PROXY2MODEL_TOKEN) to do that"), file=sys.stderr)
        return 2
    _init_key()
    outdir = os.path.join(args.out, args.webapp)
    os.makedirs(outdir, exist_ok=True)
    if args.fresh:
        _clear_inputs(outdir)
    key = f"live-{args.role}" if args.role else "live"
    live = live_serve.Live(os.path.join(_inputs_dir(outdir), key + ".jsonl"), role=args.role)
    args.label = args.label or "live"
    state = {"build": None}

    def rebuild() -> str:
        if _write_outputs(args, outdir, replace_build=state["build"], quiet=True) != 0:
            raise RuntimeError(f"could not write outputs to {outdir}")
        state["build"] = args._build_id
        args._model = None
        c = args._counts
        return "   ".join([ui.stat(c["hosts"], "host"), ui.stat(c["routes"], "route"),
                           ui.stat(c["endpoints"], "API")])

    def ready(httpd):
        flags = (f" --port {args.port}" if args.port != 8765 else "") + (" --token …" if token else "")
        print("\n".join([
            "", ui.title("serve", args.webapp), "",
            ui.row("listen", ui.style(url, "bold")),
            ui.row("output", outdir.rstrip("/") + "/"),
            ui.row("inputs", f"{live.saved} live requests" + (" kept from earlier sessions" if live.saved else "")),
            ui.row("caido", f"proxy2model serve --caido-script{flags}  " + ui.style("(passive-workflow script)", "dim")),
            "", ui.style("  waiting for traffic · Ctrl-C saves, rebuilds once more and stops", "dim"), "",
        ]), flush=True)

    def report(e: dict) -> None:
        stamp = ui.style(time.strftime("%H:%M:%S"), "dim")
        if "error" in e:
            print(f"  {stamp}  " + ui.error(f"rebuild failed: {e['error']}"), flush=True)
            return
        print(f"  {stamp}  {ui.style('+' + str(e['added']), 'green')}  {e['saved']} saved   {e['summary']}   "
              + ui.style(f"{e['seconds']:.1f}s", "dim"), flush=True)

    try:
        live_serve.serve(live, rebuild, bind=args.bind, port=args.port, token=token,
                         interval=args.interval, verbose=args.verbose, ready=ready, report=report)
    except OSError as e:
        print(ui.error(f"could not listen on {args.bind}:{args.port}: {e}"), file=sys.stderr)
        return 2
    print(f"\n  stopped · {live.saved} live requests saved in {live.path}")
    return 0
