# Deploying on Coolify (Oracle Cloud Always Free)

This app already ships a `Dockerfile` + `.dockerignore`, so Coolify deploys it
reproducibly on the Oracle Ampere **ARM64** free tier (or any x86 host). The DB
stays on Supabase — only the web app moves here.

## 1. Provision the Oracle VM (one-time)

1. **Compute → Instances → Create.** Image: **Ubuntu 24.04**. Shape: switch to
   **Ampere VM.Standard.A1.Flex**, **4 OCPU / 24 GB** (the whole free allowance).
   Paste your SSH public key.
   - If you hit *"Out of host capacity"*, retry, try another Availability Domain,
     or pick a quieter home region (home region can't be changed later).
2. **Reserve the IP:** Networking → Reserved Public IPs → convert the instance's
   ephemeral IP to **reserved** so it survives reboots.
3. **Open the firewall in BOTH layers** (the classic Oracle gotcha):
   - VCN Security List → add Ingress `0.0.0.0/0` TCP **80** and **443**.
   - On the VM, open the OS iptables too:
     ```bash
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```

## 2. Install Coolify (one-time)

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
Open `http://<reserved-ip>:8000` and create the admin account. Coolify runs its
own Traefik proxy and provisions Let's Encrypt certs automatically.

## 3. DNS

Point a name at the reserved IP (HTTPS needs a name, not a bare IP):
- **Bought domain (Cloudflare):** A record `camping` → `<ip>`, left **DNS-only
  (grey cloud)** so Coolify/Traefik can manage TLS.
- **Free:** DuckDNS subdomain → `<ip>`, or `<ip>.sslip.io` (no setup).

## 4. Create the app in Coolify

1. **New Resource → Application → Public Repository.** URL:
   `https://github.com/alex-nedelkoff/camping-planner`, branch `main`.
2. **Build Pack: Dockerfile** (auto-detected from the committed `Dockerfile`).
3. **Port: 8000** (matches `EXPOSE`/`--port 8000`).
4. **FQDN:** `https://camping.yourdomain.com` — Coolify issues the cert.
5. **Health check:** path `/healthz`, port `8000`.
6. **Environment variables** (mark secrets as such):
   ```
   STORAGE_BACKEND=postgres
   AUTH_ENABLED=true
   COOKIE_SECURE=1
   DATABASE_URL=postgresql://...@aws-1-us-east-1.pooler.supabase.com:5432/postgres
   SITE_PASSWORD=<the shared site password>
   SESSION_SECRET=<a long random string>
   ```
   Keep `DATABASE_URL` on the Supabase **IPv4 session pooler** (same value as the
   current Render deploy).
7. **Deploy.**

## 5. Auto-deploy on push

In Coolify enable the deploy webhook (or connect the GitHub App) and add it to the
repo so pushes to `main` redeploy automatically — same git-push workflow as Render.

## Notes

- **No cold start** — the VM is always on, unlike Render free's 15-min spin-down.
- **No persistent volume needed** — trips live in Postgres; the container's `trips/`
  dir is created empty at boot. (Only add a volume for `/app/trips` if you ever
  switch back to `STORAGE_BACKEND=filesystem`.)
- **Disposable VM** — code is in GitHub, data is in Supabase; the only VM-local
  state is the env vars. Keep a copy of those.
- **ARM** — every dep in `requirements-runtime.txt` has `arm64` wheels, so builds
  don't compile anything.
