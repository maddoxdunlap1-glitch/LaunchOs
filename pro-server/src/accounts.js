// LaunchOS accounts: sign up / log in with email + password, or with Google.
// Users live in the ACCOUNTS KV namespace. Sessions are signed tokens (no cookies), valid for 30 days.
// Secrets: LINK_SECRET (also signs session tokens). Var: GOOGLE_CLIENT_ID, ALLOWED_ORIGIN.

const SESSION_SECONDS = 30 * 24 * 3600;
const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/;
const PBKDF2_ITERATIONS = 100000; // the most Cloudflare Workers allows
const enc = new TextEncoder();

const toHex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const fromHex = (h) => new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16)));
const b64url = (s) => btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64url = (s) => atob(s.replace(/-/g, "+").replace(/_/g, "/"));

function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function hmacHex(secret, data) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return toHex(await crypto.subtle.sign("HMAC", key, enc.encode(data)));
}

async function hashPassword(password, saltHex) {
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: fromHex(saltHex), iterations: PBKDF2_ITERATIONS },
    key,
    256,
  );
  return toHex(bits);
}

export const normEmail = (e) => String(e || "").trim().toLowerCase();

async function makeToken(env, email) {
  const body = b64url(JSON.stringify({ e: email, x: Math.floor(Date.now() / 1000) + SESSION_SECONDS }));
  return `${body}.${await hmacHex(`session.${env.LINK_SECRET}`, body)}`;
}

// Returns the email from a valid, unexpired session token, otherwise null.
async function readToken(env, token) {
  const [body, sig] = String(token || "").split(".");
  if (!body || !sig) return null;
  if (!same(sig, await hmacHex(`session.${env.LINK_SECRET}`, body))) return null;
  try {
    const v = JSON.parse(unb64url(body));
    return v.x > Date.now() / 1000 && typeof v.e === "string" ? v.e : null;
  } catch {
    return null;
  }
}

async function profile(env, email) {
  const pro = (await env.ACCOUNTS.get(`pro:${email}`)) !== null;
  return { email, pro };
}

async function session(env, email) {
  return { ok: true, token: await makeToken(env, email), ...(await profile(env, email)) };
}

export async function signup(env, b, fail) {
  const email = normEmail(b.email);
  const password = String(b.password || "");
  if (!EMAIL_RE.test(email)) return fail(400, "bad_email");
  if (password.length < 8 || password.length > 200) return fail(400, "bad_password");
  if ((await env.ACCOUNTS.get(`user:${email}`)) !== null) return fail(409, "exists");
  const salt = toHex(crypto.getRandomValues(new Uint8Array(16)));
  const hash = await hashPassword(password, salt);
  await env.ACCOUNTS.put(`user:${email}`, JSON.stringify({ salt, hash, created: new Date().toISOString() }));
  return session(env, email);
}

export async function login(env, b, fail) {
  const email = normEmail(b.email);
  const password = String(b.password || "");
  const raw = EMAIL_RE.test(email) ? await env.ACCOUNTS.get(`user:${email}`) : null;
  const user = raw ? JSON.parse(raw) : null;
  // Do the same work whether or not the account exists, so timing does not reveal it.
  const salt = user?.salt || "00".repeat(16);
  const hash = await hashPassword(password.slice(0, 200), salt);
  if (!user || !user.hash || !same(hash, user.hash)) {
    return user && !user.hash ? fail(403, "use_google") : fail(403, "bad_login");
  }
  return session(env, email);
}

// The browser sends the Google ID token. Google checks its signature; we check it is for our app.
export async function google(env, b, fail) {
  if (!env.GOOGLE_CLIENT_ID) return fail(503, "google_not_set_up");
  const credential = String(b.credential || "");
  if (credential.length < 20 || credential.length > 4000) return fail(400, "bad_request");
  const res = await fetch(`https://oauth2.googleapis.com/tokeninfo?id_token=${encodeURIComponent(credential)}`);
  if (res.status >= 500) return fail(503, "unavailable");
  const info = await res.json().catch(() => null);
  if (!res.ok || !info || info.aud !== env.GOOGLE_CLIENT_ID) return fail(403, "bad_login");
  if (String(info.email_verified) !== "true") return fail(403, "email_not_verified");
  const email = normEmail(info.email);
  if (!EMAIL_RE.test(email)) return fail(403, "bad_login");
  if ((await env.ACCOUNTS.get(`user:${email}`)) === null) {
    await env.ACCOUNTS.put(`user:${email}`, JSON.stringify({ google: true, created: new Date().toISOString() }));
  }
  return session(env, email);
}

export async function me(env, request, fail) {
  const auth = request.headers.get("authorization") || "";
  const email = auth.startsWith("Bearer ") ? await readToken(env, auth.slice(7)) : null;
  if (!email || (await env.ACCOUNTS.get(`user:${email}`)) === null) return fail(401, "not_logged_in");
  return { ok: true, ...(await profile(env, email)) };
}

// Admin: mark an account as Pro after you see the PayPal payment.
export async function setPro(env, b, fail, on) {
  const email = normEmail(b.email);
  if (!EMAIL_RE.test(email)) return fail(400, "bad_email");
  if (on) await env.ACCOUNTS.put(`pro:${email}`, new Date().toISOString());
  else await env.ACCOUNTS.delete(`pro:${email}`);
  return { ok: true, email, pro: on };
}
