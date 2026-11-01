# Changelog

## 2.0.0

proxy2model is the new name of burp2model. Its history up to 1.3.0 is in
[falc0n-researcher/burp2model](https://github.com/falc0n-researcher/burp2model).

- **Renamed.** Package, command and module are `proxy2model`; output goes to `proxy2model-out/`.
  `BURP2MODEL_*` variables and an existing `~/.config/burp2model/fingerprint.key` still work.
- **Live capture from Caido.** `serve` takes exchanges pushed over HTTP and rebuilds the model as they
  arrive; `serve --caido-script` prints a passive-workflow script, tested in Caido with responses up
  to 7 MB. Long sessions rebuild less often so the listener stays light.
- **MCP server.** `mcp` serves built models to an AI agent (Claude Code, Claude Desktop, Cursor ...)
  with the same cited answers as the CLI. Read-only.
- **OpenAPI.** Every build writes `openapi.json`; `openapi` exports it on demand.
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
