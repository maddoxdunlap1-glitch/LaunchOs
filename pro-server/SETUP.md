# Pro server setup (you do these; I can't create accounts or secrets)

Never paste secrets in chat or commit them. Secrets go into Cloudflare with `wrangler secret put`.

## 1. Lemon Squeezy (test mode first)
1. Sign up at lemonsqueezy.com and create a store. Bank, tax and ID details are yours to enter. If sign-ups are closed, tell me and we switch to Gumroad.
2. Turn on **Test mode** (toggle at the bottom left).
3. Products > New product **LaunchOS Pro**: price $5, one-time. Under **License keys** turn them on, set **Activation limit = 5**, key length is fine at default. Put your refund text in the product description: "All sales are final. Email us if something is wrong."
4. Create a second product **Support LaunchOS** with **Pay what you want**, no license keys.
5. Note the **store ID** and **product ID** (Settings > Stores, and the product page). Put them in `wrangler.toml` as `LS_STORE_ID` and `LS_PRODUCT_ID`. They are not secret.

## 2. Cloudflare
1. Create a free account at cloudflare.com.
2. Install Node.js (LTS). In `pro-server/` run `npm install`, then `npx wrangler login`.
3. Create the private file bucket and the refund list:
   ```
   npx wrangler r2 bucket create launchos-pro-files
   npx wrangler kv namespace create REVOKED
   ```
   Paste the KV id it prints into `wrangler.toml`.
4. Make the **Pro signing key** (once; LaunchOS only installs Pro files signed with it, so even
   someone who got into your Cloudflare account couldn't push anything to Pro PCs). In Git Bash
   (it comes with Git for Windows), in a folder that is **not** inside the repo:
   ```
   openssl genpkey -algorithm ed25519 -out launchos-pro-signing.key
   openssl pkey -in launchos-pro-signing.key -pubout
   ```
   - Keep `launchos-pro-signing.key` safe (a password manager or a USB stick you keep). Never put it in the repo or on the server.
   - In GitHub: the repo > Settings > Secrets and variables > Actions > New repository secret, name `PRO_SIGNING_KEY`, value: the whole text of `launchos-pro-signing.key` (including the BEGIN/END lines).
   - The second command prints the public key: its middle line (it starts with `MCowBQYDK2VwAyEA`) goes after `signing_key=` in `src/rootfs/etc/launchos/pro.conf`, together with `url=` (step 6) and `buy=` (your Lemon Squeezy product page). Then LaunchOS is rebuilt and released with Pro on sale.
5. Make the Pro files and put them in the private bucket (never make the bucket public): GitHub >
   Actions > **Pro files** > Run workflow. It signs them with `PRO_SIGNING_KEY`. If you also add the
   secrets `CLOUDFLARE_API_TOKEN` (Cloudflare > My Profile > API Tokens, with "Workers R2 Storage:
   Edit") and `CLOUDFLARE_ACCOUNT_ID`, it uploads them itself; otherwise download the `pro-files`
   artifact from the run's page, unzip it, and upload each file:
   ```
   npx wrangler r2 object put launchos-pro-files/pro-package.tar.gz --file pro-package.tar.gz --remote
   npx wrangler r2 object put launchos-pro-files/pro-update.json --file pro-update.json --remote
   ```
   For early access, run the workflow with an **early** version (the version of the coming release, e.g. 1.1); it makes `early-update.tar.gz` and `early-update.json` too. Pro PCs move on to the real release of that number when it's out.
6. Set the three secrets (each command asks you to type the value):
   ```
   npx wrangler secret put LINK_SECRET        # any long random string
   npx wrangler secret put ADMIN_TOKEN        # any long random string, for freeing PC slots
   npx wrangler secret put LS_WEBHOOK_SECRET  # same value you type in step 3 below
   ```
7. `npx wrangler deploy`. Note the `https://launchos-pro.<you>.workers.dev` address: it's the `url=` in `pro.conf`.

## 3. Refund webhook
Lemon Squeezy > Settings > Webhooks > Add: URL `https://launchos-pro.<you>.workers.dev/webhook/lemonsqueezy`, a signing secret (the same string as `LS_WEBHOOK_SECRET`), event **order_refunded**.

## 4. Free a PC slot (when a buyer emails you)
Ask for the key. Look up the PC in Lemon Squeezy (License keys > the key > Instances) and copy the instance id, then:
```
curl -X POST https://launchos-pro.<you>.workers.dev/admin/deactivate -H "Authorization: Bearer YOUR_ADMIN_TOKEN" -d '{"key":"THE-KEY","instance_id":"THE-ID"}'
```
(Or just delete the instance in the Lemon Squeezy dashboard.)

## 5. Recommended
Add a Cloudflare rate limiting rule (Security > WAF > Rate limiting) of about 30 requests per minute per IP on the Worker's address.

## What the OS needs from the Worker (for whoever codes the OS side)
| Call | Send | Answer |
| --- | --- | --- |
| `POST /v1/activate` | `{key, pc_id}` (`pc_id` = 32 hex characters: a scrambled id of the PC's hardware, so it stays the same on that PC) | `{ok, instance_id}` or `{ok:false, error}`: `invalid_key`, `pc_limit`, `revoked`, `unavailable`. The same key + PC gets its old slot back instead of a new one. |
| `POST /v1/check` | `{key, instance_id}` | `{ok:true}` or an error. Never lock Pro because of `unavailable` or being offline; `invalid_key` only counts when seen on two different days. |
| `POST /v1/download` | `{key, instance_id, file}` (`pro-package.tar.gz`, `pro-update.json`, `early-update.*`) | `{ok, url, expires_in:600}`. Download the url within 10 minutes. The `.json` files are signed (`{payload, sig}`, Ed25519, checked against `signing_key=`); the `.tar.gz` must match the SHA-256 inside the signed JSON. |
After a refund, `/activate` and `/download` answer `revoked`. Do not delete anything from the PC.

Without `LS_STORE_ID` and `LS_PRODUCT_ID` set, the Worker accepts no key at all (it answers `unavailable`).

## 6. Accounts (login page on the website)
1. Make the accounts store: `npx wrangler kv namespace create ACCOUNTS`, paste the id into `wrangler.toml` (the `ACCOUNTS` entry).
2. Google sign-in (optional; leave `GOOGLE_CLIENT_ID` empty to hide the button): in console.cloud.google.com create a project > APIs & Services > Credentials > Create credentials > OAuth client ID > Web application. Under **Authorized JavaScript origins** add your website address (e.g. `https://maddoxdunlap1-glitch.github.io`). Copy the client ID (not a secret) into `GOOGLE_CLIENT_ID` in `wrangler.toml` and into `googleClientId` in `docs/login.html`.
3. Set `ALLOWED_ORIGIN` in `wrangler.toml` to the website address (no trailing slash), run `npx wrangler deploy`, and put the Worker address in `api` in `docs/login.html`.
4. Pro from PayPal: when a payment arrives, turn Pro on for that buyer's account email:
   ```
   curl -X POST https://launchos-pro.<you>.workers.dev/admin/grant-pro -H "Authorization: Bearer YOUR_ADMIN_TOKEN" -d '{"email":"buyer@example.com"}'
   ```
   (`/admin/revoke-pro` turns it off, e.g. after a refund.) The account page then shows Pro as Active.

Notes: email sign-ups are not verified by a confirmation email (no mail service is set up); Google sign-ins are verified by Google. Passwords are stored only as PBKDF2 hashes. Keep the rate limit rule from step 5 on, it also slows password guessing.

