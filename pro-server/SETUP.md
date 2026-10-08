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
4. Upload the Pro files (never make the bucket public):
   ```
   npx wrangler r2 object put launchos-pro-files/pro-package.tar.gz --file path/to/pro-package.tar.gz --remote
   npx wrangler r2 object put launchos-pro-files/pro-update.json --file path/to/pro-update.json --remote
   ```
5. Set the three secrets (each command asks you to type the value):
   ```
   npx wrangler secret put LINK_SECRET        # any long random string
   npx wrangler secret put ADMIN_TOKEN        # any long random string, for freeing PC slots
   npx wrangler secret put LS_WEBHOOK_SECRET  # same value you type in step 3 below
   ```
6. `npx wrangler deploy`. Note the `https://launchos-pro.<you>.workers.dev` address.

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
| `POST /v1/activate` | `{key, pc_id}` (`pc_id` = 32 random hex characters, made once per PC) | `{ok, instance_id}` or `{ok:false, error}`: `invalid_key`, `pc_limit`, `revoked`, `unavailable` |
| `POST /v1/check` | `{key, instance_id}` | `{ok:true}` or an error. Never lock Pro because of `unavailable` or being offline. |
| `POST /v1/download` | `{key, instance_id, file}` (`pro-package.tar.gz` or `pro-update.json`) | `{ok, url, expires_in:600}`. Download the url within 10 minutes, then check its SHA-256. |
After a refund, `/activate` and `/download` answer `revoked`. Do not delete anything from the PC.
