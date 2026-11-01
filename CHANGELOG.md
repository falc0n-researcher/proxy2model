# Changelog

## 2.0.0 — 2026-11-01

proxy2model is the new name of burp2model. Its history up to 1.3.0 is in
[falc0n-researcher/burp2model](https://github.com/falc0n-researcher/burp2model).

- **Renamed.** Package, command and module are `proxy2model`; output goes to `proxy2model-out/`.
  `BURP2MODEL_*` variables and an existing `~/.config/burp2model/fingerprint.key` still work.
- **Live capture.** `serve` takes exchanges pushed over HTTP (a Caido passive workflow, any script)
  and rebuilds the model as they arrive. `serve --caido-script` prints the workflow script.
- **OpenAPI.** Every build writes `openapi.json`; `openapi` exports it on demand.
- **Parameter value types.** Each parameter records the kinds of value it was seen with
  (jwt, uuid, email, integer, number, boolean, base64, string), read before masking.
- **Structured output.** `graph.json`, `graph.graphml` and `build.svg` moved to `exports/`.
  The terminal shows a short summary of what was read, what the model holds and where it went.
- **The Burp extension is gone.** The command line tool reads Burp exports as before.
