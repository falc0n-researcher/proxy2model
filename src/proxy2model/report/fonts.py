"""Fonts and type for the offline report.

The typefaces are embedded as base64 so the single-file report looks the same with no network. The
CSP allows `font-src data:` and nothing else. Nippo carries the fa1c0n field-notes look; it is a
subset (printable ASCII and a few marks), so Inter stands in for any other glyph.
"""

from __future__ import annotations

import base64
import functools
import os

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "fonts")
_FACES = [("Nippo", f"nippo-{w}.woff2", str(w)) for w in (200, 300, 400, 500, 700)] + [
    ("Inter", "inter-latin-wght-normal.woff2", "100 900"),
    ("JetBrains Mono", "jetbrains-mono-latin-wght-normal.woff2", "100 900")]


@functools.lru_cache(maxsize=1)
def font_css() -> str:
    """@font-face rules with the files inlined; empty if the files are missing (system fonts then)."""
    out = []
    for family, fn, weight in _FACES:
        try:
            with open(os.path.join(_DIR, fn), "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            return ""
        out.append(f'@font-face{{font-family:"{family}";font-style:normal;font-weight:{weight};font-display:swap;'
                   f'src:url(data:font/woff2;base64,{b64}) format("woff2")}}')
    return "\n".join(out)


# the field-notes type: Nippo throughout, light for big numbers, medium for titles; code stays mono
TYPE_CSS = r"""
:root{--sans:"Nippo","Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--display:"Nippo","Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body{letter-spacing:.005em}
h1.vt,.ovh h1,.inv-bar h1,.mtop h1{font-family:var(--display);font-weight:500;letter-spacing:-.02em}
h1.vt{font-size:28px}
.ovh h1{font-weight:300;letter-spacing:-.03em}
.big4 .n,.dk .n,.ls .n,.kpi .n,.layer .nn{font-family:var(--display);font-weight:300;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
nav.views h3{color:var(--signal);letter-spacing:.2em}
.sech h2,.dc>.h,.tile b,.card>.hd,.nlabel,.ahd,.lead .w{font-family:var(--display);font-weight:500;letter-spacing:-.01em}
.sech h2{font-size:17px}
.dc>.h,.card>.hd{font-size:14px}
.vsub,.ovh .sum{font-size:15.5px;line-height:1.6}
.kicker,nav.views h3,.minsp h3,.dnote{font-family:var(--mono)}
"""
