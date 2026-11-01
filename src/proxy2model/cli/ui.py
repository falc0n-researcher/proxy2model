"""Terminal output: a little colour on a terminal, plain text when piped or NO_COLOR is set."""

from __future__ import annotations

import os
import sys

_CODES = {"bold": "1", "dim": "2", "accent": "38;5;208", "green": "32", "yellow": "33", "red": "31", "cyan": "36"}


def color_on(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty() and os.environ.get("TERM") != "dumb"


def style(text, *names: str, stream=None) -> str:
    if not names or not color_on(stream):
        return str(text)
    return "\033[" + ";".join(_CODES[n] for n in names) + "m" + str(text) + "\033[0m"


def title(command: str, subject: str = "") -> str:
    """`proxy2model · build · shop`"""
    parts = [style("proxy2model", "bold", "accent"), style(command, "bold")]
    if subject:
        parts.append(subject)
    return style(" · ", "dim").join(parts)


def row(label: str, value: str, width: int = 8) -> str:
    """One `  label   value` line; continuation lines of `value` line up under it."""
    pad = " " * (width + 4)
    lines = str(value).split("\n")
    out = "  " + style(label.ljust(width), "dim") + "  " + lines[0]
    return "\n".join([out] + [pad + ln for ln in lines[1:]])


def stat(n, noun: str) -> str:
    """`3 routes`, `1 host`: the count bold, the noun plural when it should be."""
    return f"{style(n, 'bold')} {noun if n == 1 else noun + 's'}"


def files(entries: list[tuple[str, str]]) -> str:
    """Aligned `name   what it is` lines."""
    w = max(len(n) for n, _ in entries)
    return "\n".join(f"{n.ljust(w)}   {style(d, 'dim')}" for n, d in entries)


def ok(msg: str) -> str:
    return style("✓", "green", stream=sys.stderr) + " " + msg


def warn(msg: str) -> str:
    return style("warning:", "yellow", stream=sys.stderr) + " " + msg


def error(msg: str) -> str:
    return style("error:", "red", "bold", stream=sys.stderr) + " " + msg
