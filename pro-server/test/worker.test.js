// Runs with: npm test  (Node 20+). Lemon Squeezy, KV and R2 are faked.
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const KEY = "LOS-7F3K-9QX2-M4TD-8WBA";
const pc = (n) => n.toString(16).padStart(32, "0");

function setup() {
  const ls = { instances: new Map(), limit: 5, nextId: 1, meta: { store_id: 1, product_id: 2, order_id: 77 } };
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname.split("/").pop();
    const f = new URLSearchParams(init.body);
    const reply = (obj, status = 200) => new Response(JSON.stringify(obj), { status });
    if (f.get("license_key") !== KEY) return reply({ valid: false, activated: false, error: "not found" }, 404);
    if (path === "activate") {
      if (ls.instances.size >= ls.limit) return reply({ activated: false, error: "activation limit reached" }, 400);
      const id = `inst-${String(ls.nextId++).padStart(4, "0")}`;
      ls.instances.set(id, f.get("instance_name"));
      return reply({ activated: true, instance: { id }, license_key: { status: "active" }, meta: ls.meta });
    }
    if (path === "validate") {
      const ok = ls.instances.has(f.get("instance_id"));
      return reply({ valid: ok, license_key: { status: "active" }, meta: ls.meta });
    }
    if (path === "deactivate") {
      return reply({ deactivated: ls.instances.delete(f.get("instance_id")) });
    }
    return reply({}, 404);
  };
  const kv = new Map();
  const env = {
    LS_STORE_ID: "1",
    LS_PRODUCT_ID: "2",
    LS_WEBHOOK_SECRET: "whsec",
    LINK_SECRET: "linksec",
    ADMIN_TOKEN: "admin-token",
    REVOKED: { get: async (k) => kv.get(k) ?? null, put: async (k, v) => void kv.set(k, v) },
    PRO_FILES: { get: async (n) => (n === "pro-package.tar.gz" ? { body: "PRO", size: 3 } : null) },
  };
  return { ls, env };
}

const post = (path, body, headers = {}) =>
  new Request(`https://pro.test${path}`, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body), headers });
const call = async (env, req) => {
  const res = await worker.fetch(req, env);
  return { status: res.status, body: await res.json().catch(() => null), res };
};

async function sign(secret, text) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return [...new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(text)))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

test("buy, unlock, download", async () => {
  const { env } = setup();
  const a = await call(env, post("/v1/activate", { key: KEY, pc_id: pc(1) }));
  assert.equal(a.status, 200);
  const instance_id = a.body.instance_id;
  assert.equal((await call(env, post("/v1/check", { key: KEY, instance_id }))).status, 200);
  const d = await call(env, post("/v1/download", { key: KEY, instance_id, file: "pro-package.tar.gz" }));
  assert.equal(d.status, 200);
  assert.equal(d.body.expires_in, 600);
  const got = await worker.fetch(new Request(d.body.url), env);
  assert.equal(got.status, 200);
  assert.equal(await got.text(), "PRO");
});

test("second PC works, sixth PC is refused", async () => {
  const { env } = setup();
  for (let i = 1; i <= 5; i++) assert.equal((await call(env, post("/v1/activate", { key: KEY, pc_id: pc(i) }))).status, 200);
  const sixth = await call(env, post("/v1/activate", { key: KEY, pc_id: pc(6) }));
  assert.equal(sixth.status, 403);
  assert.equal(sixth.body.error, "pc_limit");
});

test("admin can free a slot", async () => {
  const { env } = setup();
  const ids = [];
  for (let i = 1; i <= 5; i++) ids.push((await call(env, post("/v1/activate", { key: KEY, pc_id: pc(i) }))).body.instance_id);
  const no = await call(env, post("/admin/deactivate", { key: KEY, instance_id: ids[0] }, { authorization: "Bearer wrong" }));
  assert.equal(no.status, 401);
  const yes = await call(env, post("/admin/deactivate", { key: KEY, instance_id: ids[0] }, { authorization: "Bearer admin-token" }));
  assert.equal(yes.body.ok, true);
  assert.equal((await call(env, post("/v1/activate", { key: KEY, pc_id: pc(6) }))).status, 200);
});

test("refund stops new activations and downloads, not the PC itself", async () => {
  const { env } = setup();
  const a = await call(env, post("/v1/activate", { key: KEY, pc_id: pc(1) }));
  const raw = JSON.stringify({ meta: { event_name: "order_refunded" }, data: { id: "77" } });
  const w = await call(env, post("/webhook/lemonsqueezy", raw, { "x-signature": await sign("whsec", raw) }));
  assert.equal(w.status, 200);
  const again = await call(env, post("/v1/activate", { key: KEY, pc_id: pc(2) }));
  assert.equal(again.body.error, "revoked");
  const d = await call(env, post("/v1/download", { key: KEY, instance_id: a.body.instance_id, file: "pro-update.json" }));
  assert.equal(d.body.error, "revoked");
});

test("webhook with a bad signature is refused", async () => {
  const { env } = setup();
  const raw = JSON.stringify({ meta: { event_name: "order_refunded" }, data: { id: "77" } });
  assert.equal((await call(env, post("/webhook/lemonsqueezy", raw, { "x-signature": "00" }))).status, 401);
  assert.equal(await env.REVOKED.get("order:77"), null);
});

test("wrong store, bad input, expired and tampered links are refused", async () => {
  const { env, ls } = setup();
  ls.meta = { store_id: 99, product_id: 2, order_id: 1 };
  assert.equal((await call(env, post("/v1/activate", { key: KEY, pc_id: pc(1) }))).status, 403);
  assert.equal((await call(env, post("/v1/activate", { key: "x", pc_id: "y" }))).status, 400);
  assert.equal((await call(env, post("/v1/download", { key: KEY, instance_id: "inst-0001", file: "../secret" }))).status, 400);
  const exp = Math.floor(Date.now() / 1000) - 5;
  const sig = await sign("linksec", `pro-package.tar.gz.${exp}`);
  assert.equal((await worker.fetch(new Request(`https://pro.test/v1/file/pro-package.tar.gz?exp=${exp}&sig=${sig}`), env)).status, 403);
  const exp2 = Math.floor(Date.now() / 1000) + 300;
  assert.equal((await worker.fetch(new Request(`https://pro.test/v1/file/pro-package.tar.gz?exp=${exp2}&sig=abc`), env)).status, 403);
});
