// proxy2model: push Caido traffic to `proxy2model serve` as it happens.
//
// In Caido: Workflows -> Passive -> New workflow.
//   On Intercept Response  ->  In Scope  ->  Javascript (this code)
// The In Scope node keeps the model to your target; drop it to send everything.
//
// Each request/response pair is sent as base64 raw HTTP to the local listener.
// proxy2model masks secrets as soon as it parses an exchange; nothing raw is kept.

import { RequestSpec } from "caido:utils";

const INGEST = "__INGEST_URL__";
const TOKEN = "__TOKEN__";

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

function base64(bytes) {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i], b = bytes[i + 1], c = bytes[i + 2];
    const n = (a << 16) | ((b ?? 0) << 8) | (c ?? 0);
    out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63];
    out += b === undefined ? "=" : B64[(n >> 6) & 63];
    out += c === undefined ? "=" : B64[n & 63];
  }
  return out;
}

export async function run({ request, response }, sdk) {
  if (!request) {
    return;
  }
  // never feed the listener its own traffic
  if (request.getPath() === "/ingest" && ["127.0.0.1", "localhost", "::1", "[::1]"].includes(request.getHost())) {
    return;
  }
  const payload = {
    host: request.getHost(),
    port: request.getPort(),
    tls: request.getTls(),
    request: base64(request.getRaw().toBytes()),
  };
  if (response) {
    payload.response = base64(response.getRaw().toBytes());
  }
  try {
    const spec = new RequestSpec(INGEST);
    spec.setMethod("POST");
    spec.setHeader("Content-Type", "application/json");
    if (TOKEN) {
      spec.setHeader("X-Proxy2model-Token", TOKEN);
    }
    spec.setBody(JSON.stringify(payload));
    await sdk.requests.send(spec);
  } catch (e) {
    sdk.console.log(`proxy2model: could not reach ${INGEST}: ${e}`);
  }
}
