<div align="center">

# proxy2model

**Captured proxy traffic in, an evidence-backed model of the web app out.**

Hosts, pages, scripts, endpoints, parameters, auth and the gaps in what you captured,
each tied to the request that proves it. Secrets are masked before anything is written.

[![License](https://img.shields.io/badge/license-Apache--2.0-3a424e?style=for-the-badge)](LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/falc0n-researcher/proxy2model/ci.yml?branch=main&style=for-the-badge&label=tests)](https://github.com/falc0n-researcher/proxy2model/actions/workflows/ci.yml)
[![Secrets masked](https://img.shields.io/badge/secrets-masked_before_write-0e8fd6?style=for-the-badge)](#boundaries)

<img src="assets/demo.svg" alt="proxy2model turning captured traffic into a web-app model" width="700">

</div>

## What it finds

From the bundled capture of four [OWASP Juice Shop](https://owasp.org/www-project-juice-shop/) sessions
(417 requests: anonymous, user, accounting, admin), in about two seconds on a laptop:

- **16 endpoints the app's JavaScript names but the browsing never called**: `/rest/admin`,
  `/rest/chat`, `/rest/track-order`, `/api/SecurityAnswers` ...
- **Anonymous visitors got 200 from admin-looking endpoints:**
  ```
  $ proxy2model cross-role juiceshop --low anon --high user
  'anon' reached privileged-looking endpoints (2)
    GET /rest/admin/application-configuration    ev_93  anon=[200] user=[200]
      unknown: whether the low-role response was authorised or a leak · next: compare 'anon' and 'user' response bodies
  ```
- **The observed API as OpenAPI 3.0:** 68 paths, 88 operations, ready for Postman, ZAP or a fuzzer.

Every line cites the request behind it (`ev_93`), and every lead says what is still unknown and the
next safe check. Reproduce it: `for r in anon user accountant admin; do proxy2model samples/juiceshop-$r.xml -w juiceshop --role $r; done`.

## Install

```bash
pip install git+https://github.com/falc0n-researcher/proxy2model    # Python 3.10+, no dependencies
```

## Quickstart

```bash
# From an export: Burp XML, Logger++ CSV, or HAR (browser, ZAP, mitmproxy)
proxy2model history.xml -w shop

# Live from Caido: the model rebuilds while you browse
proxy2model serve -w shop
proxy2model serve --caido-script | pbcopy    # paste into a Caido passive workflow (setup: docs/capture.md)

# Ask it questions, with no AI, or let your AI agent ask (MCP)
proxy2model query shop help
proxy2model mcp --out "$PWD/proxy2model-out"   # see docs/ai.md
```

`./demo.sh` builds the bundled sample. `proxy2model` on its own lists the everyday commands; `proxy2model <command> --help` explains each.

## Output

```
proxy2model-out/shop/
├── report.html     interactive report: overview, map, every request, query console
├── model.json      the model, and the request behind every claim
├── openapi.json    the observed API, OpenAPI 3.0
├── context.json    what to hand an AI instead of raw traffic
├── graph.db        SQLite graph, queried with `proxy2model q`
├── exports/        graph.json · graph.graphml · build.svg
└── inputs/         masked records of every capture, merged on rebuild
```

## Boundaries

| It does | It never |
| --- | --- |
| Read traffic you captured | Upload, forward or replay it |
| Mask every value before the first write | Store a token, cookie, key or PII value |
| Say what it could not observe | Claim coverage it did not have |
| Offer hypotheses and the evidence to test them | Call anything a vulnerability |

A plain build is offline. `crawl` and `osint` contact the target: use them only on systems you
are authorized to test. CI plants fake secrets in the samples and fails if one reaches any output.

## Docs

- [Capturing traffic](docs/capture.md): Burp, HAR, live from Caido (setup steps), roles
- [Crawling](docs/crawling.md): build from a running app, scripted journeys
- [The model](docs/model.md): how it is built, layer by layer
- [Querying](docs/querying.md): `query`, BQL, graph, diff
- [Using it with AI](docs/ai.md): the context package, and an MCP server for agents
- [Skill](skill/): a no-install playbook for any capable AI
