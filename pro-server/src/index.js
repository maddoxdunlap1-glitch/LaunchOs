// LaunchOS Pro server (Cloudflare Worker).
// - Checks license keys with Lemon Squeezy (it also enforces the 5-PC limit).
// - Hands out download links that expire after 10 minutes. Files live in a private R2 bucket.
// - Listens for the Lemon Squeezy refund webhook.
// Secrets (set with `wrangler secret put`, never in this repo): LS_WEBHOOK_SECRET, LINK_SECRET, ADMIN_TOKEN.

const LS = "https://api.lemonsqueezy.com/v1/licenses";
const LINK_SECONDS = 600;
const MAX_BODY = 4096;
const FILES = new Set(["pro-package.tar.gz", "pro-update.json"]);
const KEY_RE = /^[A-Za-z0-9-]{8,64}$/;
const PC_RE = /^[a-f0-9]{32}$/; // random PC id made by LaunchOS (16 random bytes, hex)
const INSTANCE_RE = /^[A-Za-z0-9-]{8,64}$/;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
const fail = (status, error) => json({ ok: false, error }, status);

const enc = new TextEncoder();
const toHex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function hmacHex(secret, data) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return toHex(await crypto.subtle.sign("HMAC", key, enc.encode(data)));
}

// Compare two strings without stopping at the first difference.
function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > MAX_BODY) return null;
  try {
    const v = JSON.parse(text);
    return v && typeof v === "object" && !Array.isArray(v) ? v : null;
  } catch {
    return null;
  }
}

async function lemon(path, fields) {
  const res = await fetch(`${LS}/${path}`, {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(fields).toString(),
  });
  let body = null;
  try {
    body = await res.json();
  } catch {}
  return { status: res.status, body: body || {} };
}

// The key must belong to our store and product (a key from someone else's Lemon Squeezy store is refused).
function ours(env, meta) {
  if (!meta) return false;
  if (env.LS_STORE_ID && String(meta.store_id) !== String(env.LS_STORE_ID)) return false;
  if (env.LS_PRODUCT_ID && String(meta.product_id) !== String(env.LS_PRODUCT_ID)) return false;
  return true;
}

async function revoked(env, meta) {
  if (!meta || meta.order_id === undefined) return false;
  return (await env.REVOKED.get(`order:${meta.order_id}`)) !== null;
}

// Check a key + PC. Returns { ok, ... } or { error, status }.
async function checkKey(env, key, instanceId) {
  const r = await lemon("validate", { license_key: key, instance_id: instanceId });
  if (r.status >= 500 || r.status === 0) return { error: "unavailable", status: 503 };
  const lk = r.body.license_key;
  if (!r.body.valid || !lk || !ours(env, r.body.meta)) return { error: "invalid_key", status: 403 };
  if (lk.status !== "active" && lk.status !== "inactive") return { error: "invalid_key", status: 403 };
  if (await revoked(env, r.body.meta)) return { error: "revoked", status: 403 };
  return { ok: true, meta: r.body.meta };
}

async function activate(request, env) {
  const b = await readJson(request);
  if (!b || !KEY_RE.test(b.key || "") || !PC_RE.test(b.pc_id || "")) return fail(400, "bad_request");
  const r = await lemon("activate", { license_key: b.key, instance_name: b.pc_id });
  if (r.status >= 500) return fail(503, "unavailable");
  const ok = r.body.activated && ours(env, r.body.meta);
  if (!ok) {
    // Lemon Squeezy says when all 5 slots are used; pass that on in plain terms.
    const msg = String(r.body.error || "").toLowerCase();
    return fail(403, msg.includes("limit") ? "pc_limit" : "invalid_key");
  }
  if (await revoked(env, r.body.meta)) {
    await lemon("deactivate", { license_key: b.key, instance_id: r.body.instance.id });
    return fail(403, "revoked");
  }
  return json({ ok: true, instance_id: r.body.instance.id });
}

async function check(request, env) {
  const b = await readJson(request);
  if (!b || !KEY_RE.test(b.key || "") || !INSTANCE_RE.test(b.instance_id || "")) return fail(400, "bad_request");
  const c = await checkKey(env, b.key, b.instance_id);
  if (!c.ok) return fail(c.status, c.error);
  return json({ ok: true });
}

// Gives a link to one allowed file. The link is signed and stops working after 10 minutes.
async function download(request, env) {
  const b = await readJson(request);
  if (!b || !KEY_RE.test(b.key || "") || !INSTANCE_RE.test(b.instance_id || "") || !FILES.has(b.file)) {
    return fail(400, "bad_request");
  }
  const c = await checkKey(env, b.key, b.instance_id);
  if (!c.ok) return fail(c.status, c.error);
  const exp = Math.floor(Date.now() / 1000) + LINK_SECONDS;
  const sig = await hmacHex(env.LINK_SECRET, `${b.file}.${exp}`);
  const origin = new URL(request.url).origin;
  return json({ ok: true, url: `${origin}/v1/file/${b.file}?exp=${exp}&sig=${sig}`, expires_in: LINK_SECONDS });
}

async function file(request, env, name) {
  if (!FILES.has(name)) return fail(404, "not_found");
  const u = new URL(request.url);
  const exp = Number(u.searchParams.get("exp"));
  const sig = u.searchParams.get("sig") || "";
  if (!Number.isInteger(exp) || exp < Date.now() / 1000) return fail(403, "expired");
  if (!same(sig, await hmacHex(env.LINK_SECRET, `${name}.${exp}`))) return fail(403, "bad_link");
  const obj = await env.PRO_FILES.get(name);
  if (!obj) return fail(404, "not_found");
  return new Response(obj.body, {
    headers: {
      "content-type": "application/octet-stream",
      "content-length": String(obj.size),
      "cache-control": "no-store",
    },
  });
}

// Lemon Squeezy refund webhook. The body is signed with HMAC-SHA256 (hex) in X-Signature.
async function webhook(request, env) {
  const raw = await request.text();
  if (raw.length > 100000) return fail(413, "too_large");
  const want = await hmacHex(env.LS_WEBHOOK_SECRET, raw);
  if (!same(request.headers.get("x-signature") || "", want)) return fail(401, "bad_signature");
  let ev;
  try {
    ev = JSON.parse(raw);
  } catch {
    return fail(400, "bad_request");
  }
  const name = ev?.meta?.event_name;
  const id = ev?.data?.id;
  if (name === "order_refunded" && /^\d{1,12}$/.test(String(id))) {
    await env.REVOKED.put(`order:${id}`, new Date().toISOString());
  }
  return json({ ok: true });
}

// You use this one by hand (see README) to free a PC slot when a buyer emails you.
async function adminDeactivate(request, env) {
  const auth = request.headers.get("authorization") || "";
  if (!env.ADMIN_TOKEN || !same(auth, `Bearer ${env.ADMIN_TOKEN}`)) return fail(401, "unauthorized");
  const b = await readJson(request);
  if (!b || !KEY_RE.test(b.key || "") || !INSTANCE_RE.test(b.instance_id || "")) return fail(400, "bad_request");
  const r = await lemon("deactivate", { license_key: b.key, instance_id: b.instance_id });
  return json({ ok: !!r.body.deactivated });
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    const m = request.method;
    try {
      if (m === "GET" && pathname.startsWith("/v1/file/")) return await file(request, env, pathname.slice(9));
      if (m !== "POST") return fail(405, "method");
      if (pathname === "/v1/activate") return await activate(request, env);
      if (pathname === "/v1/check") return await check(request, env);
      if (pathname === "/v1/download") return await download(request, env);
      if (pathname === "/webhook/lemonsqueezy") return await webhook(request, env);
      if (pathname === "/admin/deactivate") return await adminDeactivate(request, env);
      return fail(404, "not_found");
    } catch {
      return fail(500, "server_error");
    }
  },
};
