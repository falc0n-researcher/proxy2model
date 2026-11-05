"""Build the README and docs artwork: assets/readme/*.svg.

The design follows the fa1c0n field-notes profile: near-black ground, one ember accent, cream type,
Nippo embedded so GitHub renders it exactly. Every SVG is self-contained (fonts inlined), so do not
edit the output by hand; change this file and run it:

    python3 scripts/build_readme_svgs.py

The figures on the cards come from the bundled Juice Shop capture (samples/juiceshop-*.xml, four
roles). Rebuild that model and update FIGURES if the samples change.
"""

from __future__ import annotations

import base64
import os
import random
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "assets", "fonts")
OUT = os.path.join(ROOT, "assets", "readme")

INK, EMBER, CREAM, BRIGHT, MUTED, FAINT, CARD = "#0b0a08", "#e85002", "#ded2c0", "#f6f1e9", "#a39a8d", "#6f6a61", "#100e0b"

# from the four-role Juice Shop build: proxy2model samples/juiceshop-$r.xml -w juiceshop --role $r
FIGURES = {"requests": 417, "endpoints": 104, "code_only": 16, "roles": 4, "paths": 68, "ops": 88, "masked": 79,
           # proxy2model cross-role juiceshop --low anon --high user; context.json against the decoded capture
           "priv_reached": 2, "anon_writes": 2, "context_k": 37, "raw_k": 440}


def font_face() -> str:
    faces = []
    for w in (200, 300, 400, 500, 700):
        with open(os.path.join(FONTS, f"nippo-{w}.woff2"), "rb") as f:
            b = base64.b64encode(f.read()).decode()
        faces.append(f"@font-face{{font-family:'Nippo';font-style:normal;font-weight:{w};"
                     f"src:url(data:font/woff2;base64,{b}) format('woff2');}}")
    return "<style>" + "".join(faces) + "</style>"


def defs(w: int, h: int) -> str:
    return f"""<defs>
  <radialGradient id="ember" cx="82%" cy="-6%" r="60%"><stop offset="0%" stop-color="{EMBER}" stop-opacity="0.16"/><stop offset="60%" stop-color="{EMBER}" stop-opacity="0"/></radialGradient>
  <radialGradient id="ember2" cx="6%" cy="14%" r="62%"><stop offset="0%" stop-color="{EMBER}" stop-opacity="0.06"/><stop offset="64%" stop-color="{EMBER}" stop-opacity="0"/></radialGradient>
  <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#fff" stop-opacity="0.015"/><stop offset="38%" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.5 0"/></filter>
  <pattern id="grid" width="88" height="88" patternUnits="userSpaceOnUse"><path d="M88 0 H0 V88" fill="none" stroke="{CREAM}" stroke-opacity="0.03"/></pattern>
  <radialGradient id="gridmask" cx="50%" cy="20%" r="80%"><stop offset="8%" stop-color="#fff"/><stop offset="78%" stop-color="#000"/></radialGradient>
  <mask id="gm"><rect width="{w}" height="{h}" fill="url(#gridmask)"/></mask>
  <clipPath id="round"><rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="14"/></clipPath>
</defs>"""


def ground(w: int, h: int) -> str:
    return (f'<rect width="{w}" height="{h}" rx="15" fill="{INK}"/><g clip-path="url(#round)">'
            f'<rect width="{w}" height="{h}" fill="url(#grid)" mask="url(#gm)"/>'
            f'<rect width="{w}" height="{h}" fill="url(#ember)"/><rect width="{w}" height="{h}" fill="url(#ember2)"/>'
            f'<rect width="{w}" height="{h}" fill="url(#sheen)"/><rect width="{w}" height="{h}" filter="url(#grain)" opacity="0.045"/>'
            f'<rect width="{w}" height="2" fill="{EMBER}" opacity="0.55"/>')


def svg(w: int, h: int, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="Nippo">\n'
            f"{font_face()}\n{defs(w, h)}\n{body}\n</svg>\n")


def t(x, y, text, size, weight=400, fill=CREAM, anchor=None, spacing=None) -> str:
    a = f' text-anchor="{anchor}"' if anchor else ""
    s = f' letter-spacing="{spacing}px"' if spacing is not None else ""
    return f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}"{a}{s}>{escape(text)}</text>'


def caps(text: str) -> str:
    """Spaced small caps keep their spaces: SVG collapses ordinary ones."""
    return escape(text).replace(" ", "&#160;")


def pixels(seed: int, x0: int, y0: int, cols: int, rows: int, n: int) -> str:
    """The scatter of cells in the corner: a capture being read, one request at a time."""
    rnd = random.Random(seed)
    cells = rnd.sample([(c, r) for c in range(cols) for r in range(rows)], n)
    out = []
    for c, r in cells:
        hot = rnd.random() < 0.18
        op = round(rnd.uniform(0.08, 0.4) if hot else rnd.uniform(0.05, 0.32), 3)
        out.append(f'<rect x="{x0 + c * 21}" y="{y0 + r * 21}" width="20" height="20" fill="{"#f8771f" if hot else CREAM}" opacity="{op}"/>')
    return '<g opacity="0.9">' + "".join(out) + "</g>"


def corners(w: int, h: int) -> str:
    return (f'<path d="M42 48 V36 H54" stroke="{EMBER}" fill="none" opacity="0.8"/>'
            f'<path d="M{w - 42} {h - 50} V{h - 38} H{w - 54}" stroke="{EMBER}" fill="none" opacity="0.8"/>')


def mark(x: float, y: float, scale: float) -> str:
    """The falc0n mark, as on the profile hero and the falc0n.tech icon."""
    return (f'<g transform="translate({x},{y}) scale({scale})">'
            f'<path d="M37 39.5 L72 39.5 L26.5 66.5 Q43 51 46 49 Q39 45 37 39.5 Z" fill="{EMBER}"/></g>')


def hero() -> str:
    w, h, f = 1200, 430, FIGURES
    body = [ground(w, h), pixels(7, 838, 150, 14, 11, 26), corners(w, h),
            f'<text x="56" y="52" fill="{EMBER}" font-size="11.5" font-weight="500" letter-spacing="3px">{caps("FIELD NOTES · INSTRUMENT")}</text>',
            f'<line x1="290" y1="48" x2="940" y2="48" stroke="{CREAM}" stroke-opacity="0.12"/>',
            f'<text x="1144" y="52" text-anchor="end" fill="{FAINT}" font-size="11.5" letter-spacing="2.6px">{caps("OPEN SOURCE — APACHE 2.0")}</text>',
            f'<text x="56" y="108" font-size="13" font-weight="500" letter-spacing="3.4px"><tspan fill="{CREAM}">{caps("CAPTURED TRAFFIC IN  ")}</tspan>'
            f'<tspan fill="{EMBER}">&#183;</tspan><tspan fill="{CREAM}">{caps("  A MODEL OF THE APP OUT  ")}</tspan>'
            f'<tspan fill="{EMBER}">&#183;</tspan><tspan fill="{CREAM}">{caps("  PROOF FOR EVERY LINE")}</tspan></text>',
            f'<text x="56" y="224" font-size="118" font-weight="200" letter-spacing="-1px"><tspan fill="#f3ece0">proxy</tspan>'
            f'<tspan fill="{EMBER}">2</tspan><tspan fill="#f3ece0">model</tspan></text>',
            f'<text x="56" y="286" font-size="27" font-weight="300" letter-spacing="-0.3px"><tspan fill="{MUTED}">every endpoint, page and role you captured — </tspan>'
            f'<tspan fill="{BRIGHT}" font-weight="500">each tied to its request.</tspan></text>',
            f'<rect x="56" y="332" width="1088" height="46" rx="7" fill="{CARD}" stroke="{CREAM}" stroke-opacity="0.10"/>',
            f'<rect x="72" y="345" width="54" height="20" rx="4" fill="none" stroke="{EMBER}" stroke-opacity="0.5"/>',
            f'<circle cx="83" cy="355" r="3" fill="{EMBER}"><animate attributeName="opacity" values="1;0.25;1" dur="1.8s" repeatCount="indefinite"/></circle>',
            f'<text x="91" y="359" fill="{EMBER}" font-size="10" font-weight="500" letter-spacing="1.5px">LOCAL</text>',
            f'<text x="142" y="361" font-size="14.5"><tspan fill="{EMBER}">fa1c0n@recon ~ $</tspan><tspan fill="{CREAM}"> proxy2model cross-role juiceshop --low anon --high user</tspan></text>',
            f'<text x="1128" y="361" text-anchor="end" font-size="14.5" font-weight="500"><tspan fill="{BRIGHT}">{f["priv_reached"]} admin paths</tspan>'
            f'<tspan fill="{FAINT}"> &#183; </tspan><tspan fill="{BRIGHT}">{f["anon_writes"]} anon writes</tspan></text>',
            mark(1000, 22, 1.9), "</g>"]
    return svg(w, h, "\n".join(body))


def card(i: int, x: float, w: float, num: str, kind: str, title: str, big: str, lines: list[str], tags: list[str],
         foot: str, lit: bool = False) -> str:
    x1, x2 = x + 26, x + w - 26
    out = [f'<rect x="{x}" y="2" width="{w}" height="234" rx="9" fill="{CARD}" stroke="{EMBER if lit else CREAM}" stroke-opacity="{0.55 if lit else 0.12}"/>',
           f'<rect x="{x}" y="2" width="{w}" height="234" rx="9" fill="url(#sheen)"/>']
    if lit:
        out.append(f'<rect x="{x}" y="2" width="{w}" height="3" rx="1.5" fill="{EMBER}"/>')
    out += [t(x1, 40, num, 12, 500, EMBER, spacing=1.5),
            f'<text x="{x1 + 34}" y="40" fill="{FAINT}" font-size="10.5" letter-spacing="2px">{caps(kind)}</text>',
            f'<circle cx="{x2}" cy="36" r="3.5" fill="{EMBER if lit else FAINT}"/>',
            t(x1, 78, title, 22, 500, BRIGHT, spacing=-0.3),
            t(x1, 150, big, 52, 200, EMBER if lit else "#f3ece0", spacing=-1)]
    out += [t(x1, 180 + 19 * k, line, 13, 400, MUTED) for k, line in enumerate(lines[:2])]
    out.append(f'<line x1="{x1}" y1="200" x2="{x2}" y2="200" stroke="{CREAM}" stroke-opacity="0.08"/>')
    tx = x1
    for tag in tags:
        tw = 12 + len(tag) * 7.2
        out += [f'<rect x="{tx:.1f}" y="206" width="{tw:.1f}" height="18" rx="3" fill="none" stroke="{CREAM}" stroke-opacity="0.16"/>',
                t(round(tx + tw / 2, 1), 219, tag, 9.5, 400, MUTED, "middle", 1)]
        tx += tw + 7
    out.append(f'<text x="{x2}" y="220" text-anchor="end" fill="{FAINT}" font-size="10" letter-spacing="1.5px">{caps(foot)}</text>')
    return "<g>" + "".join(out) + "</g>"


def ledger() -> str:
    w, h, gap, f = 1200, 250, 22, FIGURES
    cw = (w - 2 * gap) / 3
    cards = [
        card(1, 0, cw, "001", "CROSS-ROLE", "Admin answered anonymous", "200",
             ["from /rest/admin/application-", "configuration, request cited"], ["ROLES", "API5"], "EV_93"),
        card(2, cw + gap, cw, "002", "CROSS-ROLE", "Anonymous changed a product", "PUT",
             ["/api/Products/{id} returned 200", "with no login at all"], ["ROLES", "API5"], "EV_285", lit=True),
        card(3, 2 * (cw + gap), cw, "003", "CONTEXT.JSON", "Hand an AI the model", f"{f['context_k']}k",
             [f"tokens of cited evidence instead", f"of ~{f['raw_k']}k of raw traffic"], ["AI", "MCP"], "SECRETS MASKED"),
    ]
    return svg(w, h, f'<rect width="{w}" height="{h}" fill="none"/>\n' + "\n".join(cards))


DOCS = {
    "capture": ("01", "Capturing traffic", "Burp, Caido, HAR, or a browser it records while you use the app."),
    "crawling": ("02", "Crawling a running app", "The same model from a live app: no proxy, no export, no one at the keys."),
    "model": ("03", "How it works", "Parse, mask, model, reconcile: what is in the model and how it is built."),
    "querying": ("04", "Querying the model", "Plain questions, BQL, graph reach and diffs between builds. No AI involved."),
    "ai": ("05", "Using it with an AI", "Hand an agent the evidence package, or let it ask through MCP."),
}


def banner(key: str) -> str:
    num, title, sub = DOCS[key]
    w, h = 1200, 210
    body = [ground(w, h), pixels(sum(map(ord, key)), 952, 70, 9, 6, 12), corners(w, h),
            f'<text x="56" y="52" fill="{EMBER}" font-size="11.5" font-weight="500" letter-spacing="3px">{caps("PROXY2MODEL · DOCS")}</text>',
            f'<line x1="246" y1="48" x2="940" y2="48" stroke="{CREAM}" stroke-opacity="0.12"/>',
            f'<text x="1144" y="52" text-anchor="end" fill="{FAINT}" font-size="11.5" letter-spacing="2.6px">{caps(f"{num} / {len(DOCS):02d}")}</text>',
            t(56, 124, title, 54, 200, "#f3ece0", spacing=-0.6),
            t(56, 166, sub, 19, 300, MUTED, spacing=-0.2),
            "</g>"]
    return svg(w, h, "\n".join(body))


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    files = {"hero.svg": hero(), "ledger.svg": ledger()}
    files.update({f"doc-{k}.svg": banner(k) for k in DOCS})
    for name, text in files.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote assets/readme/{name} ({len(text) // 1024} KB)")


if __name__ == "__main__":
    main()
