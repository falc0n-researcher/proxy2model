# Changelog

## 2.0.0

proxy2model is the new name of burp2model. Its history up to 1.3.0 is in
[falc0n-researcher/burp2model](https://github.com/falc0n-researcher/burp2model).

- **Renamed.** Package, command and module are `proxy2model`; output goes to `proxy2model-out/`.
  `BURP2MODEL_*` variables and an existing `~/.config/burp2model/fingerprint.key` still work.
- **`browse`: record your own browser.** Opens Chrome with a fresh profile, asks for the URL, scope
  (`*.example.com`) and mode, and records every in-scope request of every tab, popup, frame and
  worker while you use the app. The model rebuilds as you go. **Active** mode also crawls in a
  background tab of the same browser, sharing your login, GET only unless `--allow-writes`. It asks
  for a role, can keep the login between sessions (`--keep-login`), skips images, fonts and
  stylesheets, records WebSocket handshakes, and ends with the code-only endpoints to visit next.
- **Caido exports.** A Caido HTTP history export (JSON or CSV) builds like a Burp export; its
  `source` filters with `--skip-tools` / `--only-tools`. `watch` also picks up `*.json`.
- **Report.** An **Endpoints** page lists the whole API in one sortable table (seen in traffic or
  only in code, status, parameters, credential, roles, leads) with the request below. Leads that
  share a reason, and open questions that share an unknown, say it once. With one role captured,
  the access-control questions point to the one capture that answers them. Links use the names the
  nav shows (`#map`, `#requests`, `#check`, `#endpoints`). An endpoint named only in code shows
  `ANY`, not `*`. Numbers in beautified code stay on their line, and To check opens at once.
- **MCP server.** `mcp` serves built models to an AI agent (Claude Code, Claude Desktop, Cursor ...)
  with the same cited answers as the CLI. Read-only.
- **OpenAPI.** Every build writes `openapi.json`, with response schemas read from JSON bodies;
  `openapi` exports it on demand.
- **Less noise.** Bot-detection and challenge posts (Akamai, Cloudflare, PerimeterX, Kasada, Imperva)
  are not counted as endpoints. A reference whose base URL is a variable is shown as `{base}/...`
  instead of being pinned to the page's host.
- **Parameter value types.** Each parameter records the kinds of value it was seen with
  (jwt, uuid, email, integer, number, boolean, base64, string), read before masking. Items of a JSON
  array share one name (`$.events[].id`) instead of one parameter per item.
- **Echoed secrets are masked.** A cookie or credential value is masked wherever else the exchange
  repeats it (found in a real capture: a cookie echoed in a response header).
- **Structured output.** `graph.json`, `graph.graphml` and `build.svg` moved to `exports/`. The
  terminal shows what was read, what the model holds and where it went; `proxy2model` alone lists
  the six everyday commands.
- **Requires Python 3.10.**
- **The Burp extension is gone.** The command line tool reads Burp exports as before.
