# Capturing traffic

proxy2model reads traffic you already captured, or takes it live. Only capture traffic you are
authorized to record. Everything runs locally.

## Burp Suite

1. Set **Target > Scope** and browse the app through Burp as the role you want to capture.
2. In **Proxy > HTTP history**, select all, right-click, **Save items**. Keep base64 encoding on.

```bash
proxy2model history.xml -w shop
```

Burp Community is enough. A **Logger++ CSV** works too (`--skip-tools Scanner` drops scanner rows).

## HAR (browser, Caido, ZAP, mitmproxy, Hetty, Charles)

```bash
proxy2model session.har -w shop
```

In a browser: DevTools, Network, *Save all as HAR with content*. Requests that never got a response are skipped.

## Live, from Caido or a script

`serve` keeps the model up to date while you browse: a proxy pushes each exchange to a local
listener and the model, report and `openapi.json` rebuild a few seconds later.

```bash
proxy2model serve -w shop                 # listens on http://127.0.0.1:8765/ingest
proxy2model serve --caido-script          # prints the Caido workflow script
```

In Caido, create a passive workflow **On Intercept Response → In Scope → Javascript** and paste
the script into the Javascript node. Anything else can POST JSON:

```bash
curl -s http://127.0.0.1:8765/ingest -H 'Content-Type: application/json' -d '{
  "request":  "'"$(printf 'GET /api/users/7 HTTP/1.1\r\nHost: shop.test\r\n\r\n' | base64)"'",
  "response": "'"$(printf 'HTTP/1.1 200 OK\r\n\r\n{}' | base64)"'"
}'
```

The script sends at most 64 KB of an ordinary body and 2 MB of a page or script, and marks what it cut.
If it fails inside Caido, `serve` prints the error.

`request` and `response` are base64 raw HTTP; `host`, `port` and `tls` are optional. Batches go
as `{"items": [...]}`. Each exchange is masked on arrival and only the masked record is saved
(`inputs/live.jsonl`), so a restart continues where it stopped. A session is one build in the history.

The listener binds `127.0.0.1`, accepts only JSON with a loopback `Host` header, and needs
`--token` to bind anything else.

## Roles

Capture once per role, then compare:

```bash
proxy2model user.xml  -w shop --role user
proxy2model admin.xml -w shop --role admin
proxy2model cross-role shop --low user --high admin
```

Rebuilding a role replaces only that role; a build without `--role`, or with `--fresh`, starts over.

## Keep exporting

`proxy2model watch FOLDER -w shop` builds every new export dropped into the folder and prints what changed.

## No proxy

`proxy2model crawl https://shop.example.com/ -w shop --yes` drives a real browser. See [crawling.md](crawling.md).
