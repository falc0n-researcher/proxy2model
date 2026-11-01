"""
Infer what kind of value a parameter carries, from its raw value.

Runs in parse.py before values are masked, so only the label survives — the
value itself never reaches the model. The checks run as a waterfall, most
specific first, and the first match wins:

    jwt -> uuid -> email -> integer -> number -> boolean -> base64 -> string

An empty value says nothing about its type and yields None.
"""

from __future__ import annotations

import re

TYPES = ("jwt", "uuid", "email", "integer", "number", "boolean", "base64", "string")

# ASCII classes only, so the Java engine (Infer.java) labels every value the same way
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_INT_RE = re.compile(r"-?[0-9]{1,19}")
_NUM_RE = re.compile(r"-?[0-9]+\.[0-9]+(?:[eE][+-]?[0-9]+)?")
_B64_RE = re.compile(r"[A-Za-z0-9+/]+")
_B64URL_RE = re.compile(r"[A-Za-z0-9_-]+")
_UPPER_RE = re.compile(r"[A-Z]")
_LOWER_RE = re.compile(r"[a-z]")
_B64_TELL_RE = re.compile(r"[0-9+/=_-]")


def _is_base64(v: str) -> bool:
    # short alphanumerics (`admin`, `true1`) are valid base64 by accident: demand
    # length, well-formed padding, and the mix of cases and digits words rarely have
    core = v.rstrip("=")
    pad = len(v) - len(core)
    if pad > 2 or (pad and len(v) % 4) or len(core) < 12 or len(core) % 4 == 1:
        return False
    if not (_B64_RE.fullmatch(core) or _B64URL_RE.fullmatch(core)):
        return False
    return bool(_B64_TELL_RE.search(v) and _UPPER_RE.search(v) and _LOWER_RE.search(v))


def value_type(value: str | None) -> str | None:
    """The type label for one raw value, or None when it is empty."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if _JWT_RE.fullmatch(v):
        return "jwt"
    if _UUID_RE.fullmatch(v):
        return "uuid"
    if _EMAIL_RE.fullmatch(v):
        return "email"
    if _INT_RE.fullmatch(v):
        return "integer"
    if _NUM_RE.fullmatch(v):
        return "number"
    if v.lower() in ("true", "false"):
        return "boolean"
    if _is_base64(v):
        return "base64"
    return "string"


def param_types(location: str, params: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """(location, name, type) for each parameter whose value has a type."""
    out = []
    for name, value in params:
        t = value_type(value)
        if t is not None:
            out.append((location, name, t))
    return out
