"""
Live capture: exchanges recorded while you browse are masked as they arrive, appended to
`inputs/browse.jsonl`, and the model is rebuilt every few seconds while anything new comes in.

Only the masked record is ever written; a restart continues where the last session stopped.
"""

from __future__ import annotations

import json
import os
import threading
import time
from xml.etree.ElementTree import Element

from .parse import Exchange, parse_elements


class Live:
    """Masked exchanges waiting to be saved, and the file they are appended to."""

    def __init__(self, path: str, role: str | None = None):
        self.path = path
        self.role = role
        self.lock = threading.Lock()
        self.pending: list[Exchange] = []
        self.stats = {"items": 0, "parsed": 0, "skipped": 0}
        self.received = 0
        self.saved = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.saved = sum(1 for line in f if line.strip() and '"_stats"' not in line[:12])

    def ingest(self, items: list[Element]) -> tuple[int, int]:
        """Parse and mask each recorded <item>; returns (accepted, skipped)."""
        stats: dict = {}
        parsed = list(parse_elements(items, source="live", role=self.role, stats=stats))
        skipped = len(items) - len(parsed)
        with self.lock:
            for ex in parsed:
                ex.item = self.saved + len(self.pending)
                self.pending.append(ex)
            self.stats["items"] += len(items)
            self.stats["parsed"] += len(parsed)
            self.stats["skipped"] += skipped
            self.received += len(parsed)
        return len(parsed), skipped

    def flush(self) -> int:
        """Append what is pending to the input file in one write; returns how many were saved."""
        with self.lock:
            batch, stats = self.pending, self.stats
            self.pending, self.stats = [], {"items": 0, "parsed": 0, "skipped": 0}
        if not batch and not stats["items"]:
            return 0
        lines = [json.dumps(ex.to_record()) for ex in batch]
        lines.append(json.dumps({"_stats": stats, "_version": 1}))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.saved += len(batch)
        return len(batch)


class Rebuilder(threading.Thread):
    """Every `interval` seconds, saves what arrived and, if anything did, rebuilds.

    `report` gets one dict per rebuild: {"added", "saved", "summary", "seconds"}, or {"error"}."""

    def __init__(self, live: Live, rebuild, interval: float, report=print):
        super().__init__(daemon=True)
        self.live, self.rebuild, self.interval, self.report = live, rebuild, interval, report
        self.stop = threading.Event()
        self.last = 0.0                              # how long the last rebuild took

    def step(self) -> None:
        n = self.live.flush()
        if not n:
            return
        t0 = time.monotonic()
        try:
            summary = self.rebuild()
        except Exception as e:                      # a bad rebuild must not stop the listener
            self.report({"error": str(e)})
        else:
            self.report({"added": n, "saved": self.live.saved, "summary": summary,
                         "seconds": time.monotonic() - t0})
        self.last = time.monotonic() - t0

    def run(self) -> None:
        # a big session rebuilds slowly: wait at least twice as long as the last rebuild took,
        # so the listener never spends more than a third of its time rebuilding
        while not self.stop.wait(max(self.interval, 2 * self.last)):
            self.step()
