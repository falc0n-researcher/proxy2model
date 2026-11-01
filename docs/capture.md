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

## HAR (browser, ZAP, mitmproxy, Hetty, Charles)

```bash
proxy2model session.har -w shop
```

In a browser: DevTools, Network, *Save all as HAR with content*. Requests that never got a response are skipped.

## Live from Caido

The model rebuilds a few seconds after each request you make in Caido. No exports.

1. Start the listener:
   ```bash
   proxy2model serve -w shop
   ```
2. Print the workflow script with `proxy2model serve --caido-script` and copy it
   (`| pbcopy` on macOS). Add `--port` or `--token` if you use them; the script is filled in with both.
3. In Caido, open a project, then **Workflows → Passive → New workflow**:
   **On Intercept Response → In Scope → Javascript**. Paste the script into the Javascript node,
   save, and make sure the workflow is enabled.
4. Set your scope in Caido and browse. `serve` prints a line for each rebuild:
   ```
   23:41:53  +3  22 saved   1 host   6 routes   7 APIs   0.0s
   ```

Without the In Scope node, everything Caido proxies is sent.

**Nothing arrives?** Check that a Caido project is open (without one Caido proxies nothing), that
the workflow is saved and enabled, and that `serve` is running. If the script fails inside Caido,
`serve` prints its error.

The script sends at most 64 KB of an ordinary body and 2 MB of a page or script (all proxy2model
uses), and marks what it cut. Each exchange is masked on arrival and only the masked record is
saved (`inputs/live.jsonl`), so a restart continues where it stopped. A session is one build in the history.

## Live from a script

Anything that can POST JSON can feed `serve`:

```bash
curl -s http://127.0.0.1:8765/ingest -H 'Content-Type: application/json' -d '{
  "request":  "'"$(printf 'GET /api/users/7 HTTP/1.1\r\nHost: shop.test\r\n\r\n' | base64)"'",
  "response": "'"$(printf 'HTTP/1.1 200 OK\r\n\r\n{}' | base64)"'"
}'
```

`request` and `response` are base64 raw HTTP; `host`, `port` and `tls` are optional. Batches go
as `{"items": [...]}`.

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
