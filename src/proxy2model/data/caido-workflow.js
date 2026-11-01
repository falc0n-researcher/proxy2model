// proxy2model: push Caido traffic to `proxy2model serve` as it happens.
//
// In Caido, with a project open: Workflows -> Passive -> New workflow.
//   On Intercept Response  ->  In Scope  ->  Javascript (this code)
// The In Scope node keeps the model to your target; drop it to send everything.
//
// Each request/response pair is sent as base64 raw HTTP to the local listener.
// proxy2model masks secrets as soon as it parses an exchange; nothing raw is kept.

import { RequestSpec } from "caido:utils";

// `proxy2model serve --caido-script` fills these in for its --port and --token.
const INGEST = "http://127.0.0.1:8765/ingest";
const TOKEN = "";

// proxy2model keeps 20 KB of an ordinary body and scans pages and scripts for the endpoints
// they name, so more than this is never used. Cut bodies are marked as truncated.
const MAX_BODY = 64 * 1024;
const MAX_CODE = 2 * 1024 * 1024;

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const PAIRS = [];
for (let i = 0; i < 4096; i++) {
  PAIRS.push(B64[i >> 6] + B64[i & 63]);
}

// Only index access and .length are used on Caido's byte arrays: other array methods are
// not guaranteed there. Chunked and table-driven, because building one long string a
// character at a time is quadratic in Caido's JavaScript engine (a 1 MB body took 10 s).
function base64(bytes, length) {
  const parts = [];
  const full = length - (length % 3);
  for (let start = 0; start < full; start += 24576) {
    const end = Math.min(start + 24576, full);
    const chunk = [];
    for (let i = start; i < end; i += 3) {
      const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
      chunk.push(PAIRS[n >> 12], PAIRS[n & 4095]);
    }
    parts.push(chunk.join(""));
  }
  const rest = length - full;
  if (rest === 1) {
    const n = bytes[full] << 16;
    parts.push(B64[n >> 18] + B64[(n >> 12) & 63] + "==");
  } else if (rest === 2) {
    const n = (bytes[full] << 16) | (bytes[full + 1] << 8);
    parts.push(B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + "=");
  }
  return parts.join("");
}

// How much of a message to send: the whole head, and as much body as proxy2model can use.
function keep(bytes) {
  const stop = Math.min(bytes.length, 65536);         // heads are small
  let end = stop;
  for (let i = 0; i + 3 < stop; i++) {
    if (bytes[i] === 13 && bytes[i + 1] === 10 && bytes[i + 2] === 13 && bytes[i + 3] === 10) {
      end = i + 4;
      break;
    }
  }
  const head = [];
  for (let i = 0; i < Math.min(end, 16384); i++) {
    head.push(String.fromCharCode(bytes[i]));
  }
  const code = /content-type:[^\r\n]*(html|javascript|ecmascript)/i.test(head.join(""));
  const limit = end + (code ? MAX_CODE : MAX_BODY);
  return bytes.length > limit ? { length: limit, truncated: true } : { length: bytes.length, truncated: false };
}

async function post(sdk, body) {
  const spec = new RequestSpec(INGEST);
  spec.setMethod("POST");
  spec.setHeader("Content-Type", "application/json");
  if (TOKEN) {
    spec.setHeader("X-Proxy2model-Token", TOKEN);
  }
  spec.setBody(JSON.stringify(body));
  await sdk.requests.send(spec);
}

export async function run({ request, response }, sdk) {
  if (!request) {
    return;
  }
  // never feed the listener its own traffic
  if (request.getPath() === "/ingest" && ["127.0.0.1", "localhost", "::1", "[::1]"].includes(request.getHost())) {
    return;
  }
  let payload;
  try {
    const rq = request.getRaw().toBytes();
    const rqKeep = keep(rq);
    payload = {
      host: request.getHost(),
      port: request.getPort(),
      tls: request.getTls(),
      request: base64(rq, rqKeep.length),
      truncated: rqKeep.truncated,
    };
    if (response) {
      const rs = response.getRaw().toBytes();
      const rsKeep = keep(rs);
      payload.response = base64(rs, rsKeep.length);
      payload.truncated = rqKeep.truncated || rsKeep.truncated;
    }
  } catch (e) {
    payload = { script_error: String(e && e.stack ? e.stack : e).slice(0, 2000) };   // shown by `serve`
  }
  try {
    await post(sdk, payload);
  } catch (e) {
    sdk.console.log(`proxy2model: could not reach ${INGEST}: ${e}`);
  }
}
