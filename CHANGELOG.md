# Changelog

## Unreleased

- **Caido workflow, tested in Caido.** The script sends at most 64 KB of an ordinary body and 2 MB of
  a page or script (what proxy2model can use), marks cut bodies as truncated, and encodes in chunks:
  a 7 MB response now arrives in about 0.1 s instead of never. It works as copied from the repo
  (defaults to `127.0.0.1:8765`), and an error inside it is printed by `serve`.
- **`serve` keeps connections open.** Some exchanges from Caido were lost without an error when the
  listener closed each connection; with keep-alive, 235 of 235 arrived in testing.

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
