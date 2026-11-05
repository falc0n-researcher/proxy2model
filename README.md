<!-- ─────────────────────────────────────────────────────────────
     proxy2model · README
     The artwork in assets/readme/ is self-contained SVG (Nippo embedded).
     Do not edit it by hand: change scripts/build_readme_svgs.py and run it.
     Links are absolute so the same file renders on PyPI.
     ───────────────────────────────────────────────────────────── -->

<img src="https://raw.githubusercontent.com/falc0n-researcher/proxy2model/main/assets/readme/hero.svg" alt="proxy2model: every endpoint, page and role you captured, each tied to its request" width="100%">

### `//` the instrument

**Every claim cites the request that proves it, and the model names what the capture could not see.**
proxy2model turns the traffic you already capture into a model of the web app: its endpoints, pages,
parameters and roles. It compares what each role reached and hands an AI cited evidence instead of
raw traffic. It does not scan or attack, and it never calls anything a vulnerability: it gives
hypotheses and the next safe check.

[![pypi](https://img.shields.io/pypi/v/proxy2model?style=flat-square&labelColor=0b0a08&color=e85002)](https://pypi.org/project/proxy2model/)
[![tests](https://img.shields.io/github/actions/workflow/status/falc0n-researcher/proxy2model/ci.yml?branch=main&style=flat-square&label=tests&labelColor=0b0a08&color=ded2c0)](https://github.com/falc0n-researcher/proxy2model/actions/workflows/ci.yml)
[![secrets](https://img.shields.io/badge/secrets-masked%20before%20write-ded2c0?style=flat-square&labelColor=0b0a08)](#-boundaries)
[![license](https://img.shields.io/badge/license-apache--2.0-6f6a61?style=flat-square&labelColor=0b0a08)](https://github.com/falc0n-researcher/proxy2model/blob/main/LICENSE)

```bash
git clone https://github.com/falc0n-researcher/proxy2model && cd proxy2model && ./demo.sh
```

Sixty seconds, nothing to install, no network: four recorded OWASP Juice Shop sessions are modelled,
anonymous is compared with a signed-in user, the surface the login opened is diffed, and the report opens.

---

### `//` cross-role — what each role should not have reached

<img src="https://raw.githubusercontent.com/falc0n-researcher/proxy2model/main/assets/readme/ledger.svg" alt="From the Juice Shop sample: an admin endpoint answered anonymous with 200, anonymous changed a product with PUT, and context.json is 37k tokens instead of about 440k of raw traffic" width="100%">

Record the app once per role (`--role anon`, `--role user`, ...) and ask what the lower one reached:

```
$ proxy2model cross-role juiceshop --low anon --high user
anon vs user: 2 privileged-looking reached · 3 object reads to test · 2 writes by anon · 31 untested · 12 enforced

'anon' reached privileged-looking endpoints (2)  [function-level authorization (OWASP API5)]
  GET /rest/admin/application-configuration    ev_93  anon=[200] user=[200]
    unknown: whether the low-role response was authorised or a leak · next: compare 'anon' and 'user' response bodies

'anon' changed state (2)  [function-level authorization (OWASP API5)]
  PUT /api/Products/{id}                       ev_285  anon=[200]
    unknown: whether 'anon' may PUT here on a record it does not own · next: confirm in the app's design ...
```

Each divergence is named for the question it raises:

| Intent | What it means | The next safe check |
| --- | --- | --- |
| privileged-looking reached | the low role got through to an admin-style path | compare both roles' response bodies |
| object reads | the low role read an object by id (a BOLA question) | ask for another account's id as the low role |
| writes | the low role changed state and got a 2xx | confirm the design allows it, on a record you own |
| untested | only the high role ever tried it | replay it as the low role |
| enforced | 401/403 for the low role, 2xx for the high | the control every other replay is compared with |

---

### `//` hand an AI the model, not the traffic

Raw traffic pasted into an LLM is huge, full of secrets, and invites guessing. `context.json` is the
model packed for an AI: about **37k tokens for the Juice Shop capture instead of ~440k**, every value
masked, every fact tied to an evidence id, and rules the model must follow:

```
Cite an evidence id (ev_N) for every claim; each id is resolved in `evidence`.
Never name an endpoint, route or parameter that is not in this package.
State unknowns explicitly; do not guess authorization behaviour.
Treat an absence in this package as an absence in the capture, never in the target.
```

Or let an agent ask the model itself over MCP (`proxy2model mcp`): the same cited answers as the CLI,
read-only. The [skill](https://github.com/falc0n-researcher/proxy2model/tree/main/skill) is the method as a playbook an AI follows, nothing to install.

---

### `//` diff — what changed since the last capture

Every build is kept. Capture the app again next week, or as another role, and ask what moved:

```
$ proxy2model diff juiceshop demo-anon demo-user
  1 new workflow(s) · 24 new · 42 changed · 3 gone
  ▸ route /profile  (79 things: 2 routes, 29 endpoints, 45 parameters, 2 auths, 1 role)
      /profile → /rest/user/change-password → DELETE /api/Addresss/{id} → ...
```

New workflows, changed fingerprints and what is gone, each with its requests: drift, never findings.
`proxy2model watch` builds every export dropped into a folder and prints the change.

---

### `//` intake

| Traffic from | Command |
| --- | --- |
| Burp (*Save items* XML), Logger++ CSV, Caido (JSON or CSV), or a HAR (browser, ZAP, mitmproxy) | `proxy2model FILE -w app` |
| A browser it opens and records while you use the app | `proxy2model browse` |
| A crawl of a running app | `proxy2model crawl URL -w app --yes` |

Every value is masked as it is read. One model comes out: a report, a SQLite graph you can query,
OpenAPI, and a compact package for an AI. Runs locally.

```bash
pip install proxy2model
```

```bash
proxy2model history.xml -w shop     # build from an export
proxy2model browse                  # or open a browser and use the app (asks for URL, scope, mode)

proxy2model query shop help         # ask the model; answers cite requests, no AI involved
proxy2model mcp --out "$PWD/proxy2model-out"   # or let an AI agent ask (see Using it with an AI)
```

`proxy2model` on its own lists the everyday commands; `proxy2model <command> --help` explains each.

---

### `//` what comes out

```
proxy2model-out/shop/
├── report.html     interactive report: overview, what to check, endpoints, map, every request, query console
├── model.json      the model, and the request behind every claim
├── openapi.json    the observed API, OpenAPI 3.0
├── context.json    what to hand an AI instead of raw traffic
├── graph.db        SQLite graph, queried with `proxy2model q`
├── exports/        graph.json · graph.graphml · build.svg
└── inputs/         masked records of every capture, merged on rebuild
```

---

### `//` boundaries

| It does | It never |
| --- | --- |
| Read traffic you captured | Upload, forward or replay it |
| Mask every value before the first write | Store a token, cookie, key or PII value |
| Say what it could not observe | Claim coverage it did not have |
| Offer hypotheses and the evidence to test them | Call anything a vulnerability |

A plain build is offline. `crawl`, `browse --active` and `osint` send requests of their own: use
them only on systems you are authorized to test. CI plants fake secrets in the samples and fails if
one reaches any output.

---

### `//` field manual

- **01 · [Capturing traffic](https://github.com/falc0n-researcher/proxy2model/blob/main/docs/capture.md)** — Burp, Caido, HAR, `browse`, roles.
- **02 · [Crawling a running app](https://github.com/falc0n-researcher/proxy2model/blob/main/docs/crawling.md)** — `crawl` and scripted journeys.
- **03 · [How it works](https://github.com/falc0n-researcher/proxy2model/blob/main/docs/model.md)** — what is in the model and how it is built.
- **04 · [Querying the model](https://github.com/falc0n-researcher/proxy2model/blob/main/docs/querying.md)** — `query`, BQL, graph reach, diffs between builds.
- **05 · [Using it with an AI](https://github.com/falc0n-researcher/proxy2model/blob/main/docs/ai.md)** — `context.json` and the MCP server.
- **[Skill](https://github.com/falc0n-researcher/proxy2model/tree/main/skill)** — the same method as a playbook for an AI, nothing to install.

<sub>`fa1c0n@recon ~ $` &nbsp; every claim cites a request · every gap is named</sub>
