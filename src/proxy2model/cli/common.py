"""Shared by the commands: names, the fingerprint key, saved inputs, loading a model."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from ..atomic import atomic_write
from ..ingest.parse import Exchange
from ..core.model import from_dict
from ..ingest.redact import set_fingerprint_key
from ..db import store


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


DEFAULT_INPUT = "_default"
EXPORTS = "exports"            # graph.json, graph.graphml and build.svg, inside the model folder


def _name(kind: str):
    def check(value: str) -> str:
        if not _NAME_RE.match(value):
            raise argparse.ArgumentTypeError(
                f"{kind} must be letters, digits, '.', '_' or '-' (got {value!r})")
        return value
    return check


def _init_key() -> None:
    """Keep one fingerprint key per user, outside any output directory.

    Fingerprints from separate runs (e.g. one per role) must be comparable, but
    the key must not travel with the outputs — otherwise anyone holding
    model.json could confirm a guessed secret against its fingerprint.
    """
    if os.environ.get("PROXY2MODEL_FP_KEY"):
        return
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "proxy2model", "fingerprint.key")
    old = os.path.join(base, "burp2model", "fingerprint.key")
    if not os.path.exists(path) and os.path.exists(old) and os.path.getsize(old) >= 16:
        path = old          # keep fingerprints comparable with builds made before the rename
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 16:
            # never run with a missing, empty or truncated key
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with atomic_write(path, "wb", perms=0o600) as f:      # whole or absent, never half a key
                f.write(os.urandom(32))
        with open(path, "rb") as f:
            set_fingerprint_key(f.read())
    except OSError as e:
        print(f"warning: no persistent fingerprint key ({e}); fingerprints from "
              "separate runs will not match", file=sys.stderr)


def _inputs_dir(outdir: str) -> str:
    return os.path.join(outdir, "inputs")


INPUTS_VERSION = 1


def _save_input(outdir: str, key: str, exchanges: list[Exchange], stats: dict) -> None:
    d = _inputs_dir(outdir)
    os.makedirs(d, exist_ok=True)
    with atomic_write(os.path.join(d, key + ".jsonl")) as f:
        f.write(json.dumps({"_stats": stats, "_version": INPUTS_VERSION}) + "\n")
        for ex in exchanges:
            f.write(json.dumps(ex.to_record()) + "\n")


def _stage_input(outdir: str, exchanges, stats: dict) -> tuple[str, int]:
    """Write parsed exchanges straight to a staging file as they stream in, so a large export is never
    held in memory. The stats line goes last, when the counts are final. Returns (path, exchanges written)."""
    d = _inputs_dir(outdir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, ".staging")
    n = 0
    try:
        with open(path, "w", encoding="utf-8") as f:
            for ex in exchanges:
                f.write(json.dumps(ex.to_record()) + "\n")
                n += 1
            f.write(json.dumps({"_stats": stats, "_version": INPUTS_VERSION}) + "\n")
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path, n


def _drop_if_empty(outdir: str) -> None:
    """A build that read nothing leaves no folders behind."""
    for d in (_inputs_dir(outdir), outdir):
        try:
            os.rmdir(d)
        except OSError:
            pass


def _clear_inputs(outdir: str, only: str | None = None, keep: str | None = None) -> None:
    d = _inputs_dir(outdir)
    if not os.path.isdir(d):
        return
    for fn in os.listdir(d):
        if fn.endswith(".jsonl") and (only is None or fn == only + ".jsonl") and fn != f"{keep}.jsonl":
            os.remove(os.path.join(d, fn))


def _load_inputs(outdir: str) -> tuple[list[Exchange], dict, list[str]]:
    """All saved inputs, re-indexed so evidence ids are unique across them."""
    d = _inputs_dir(outdir)
    exchanges: list[Exchange] = []
    stats = {"items": 0, "parsed": 0, "skipped": 0}
    names = []
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.endswith(".jsonl"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                loaded = []
                for line in f:
                    rec = json.loads(line)
                    if "_stats" in rec:
                        if rec.get("_version", 1) > INPUTS_VERSION:
                            raise ValueError(f"saved by a newer proxy2model "
                                             f"(inputs v{rec['_version']})")
                        for k in stats:
                            stats[k] += rec["_stats"].get(k, 0)
                        continue
                    loaded.append(Exchange.from_record(rec))
        except (ValueError, KeyError, TypeError) as e:
            print(f"warning: skipping unreadable saved input {fn}: {e}\n"
                  f"  re-run the build for that capture (or use --fresh)", file=sys.stderr)
            continue
        names.append(fn[:-6])
        for ex in loaded:
            ex.index = len(exchanges) + 1
            exchanges.append(ex)
    return exchanges, stats, names


def _scope(args) -> list[str] | None:
    """Normalise --scope values: accept `https://shop.com:443/x` for `shop.com`."""
    if not args.scope:
        return None
    out = []
    for s in args.scope:
        for x in s.split(","):
            x = x.strip().lower()
            if not x:
                continue
            x = re.sub(r"^[a-z][a-z0-9+.-]*://", "", x)   # scheme
            x = x.split("/")[0]                            # path
            if not x.startswith("[") and x.count(":") == 1:
                x = x.split(":")[0]                        # port
            if x:
                out.append(x)
    return out or None


def _db_path(args) -> str | None:
    path = os.path.join(args.out, args.webapp, store.DB_NAME)
    if not os.path.exists(path):
        print(f"no graph database at {path} — run `proxy2model build` first", file=sys.stderr)
        return None
    return path


def _model_path(args) -> str | None:
    path = os.path.join(args.out, args.webapp, "model.json")
    if not os.path.exists(path):
        print(f"no model at {path} — run `proxy2model build` first", file=sys.stderr)
        return None
    return path


def _reload(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return from_dict(json.load(f))
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"could not load {path}: {e}\nre-run `proxy2model build` to regenerate it.",
              file=sys.stderr)
        return None
