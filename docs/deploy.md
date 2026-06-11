# Deployment — single-host VPS (Caddy + Docker)

Target: one low-spec US VPS running Ubuntu LTS, Caddy serving the rendered
static site, the weekly pipeline running as a one-shot Docker container.
Public surface is **static files only** — no app runtime, no database, no
secrets reachable from the internet.

## 0. Provision

**Provider:** Hetzner Cloud (US — Ashburn or Hillsboro). A `CPX11` (2 vCPU,
2 GB RAM) is plenty; Chromium during the weekly run is the only spiky load
and there's no concurrent traffic to worry about.

- OS: Ubuntu 24.04 LTS
- Add your SSH public key during creation
- Note the public IPv4 (you'll need it for DNS)

## 1. Initial hardening (as root, first SSH in)

This box is operated as **root over SSH (key-only)** — it's single-purpose,
so there's no benefit to a sudo dance. The pipeline still runs **non-root
inside the container** (uid 1000, see step 5), which is where the actual
untrusted work happens. A named admin user / SSO can be layered on later
without touching anything below.

```bash
# Patch + auto-updates
apt update && apt -y full-upgrade
apt -y install ufw fail2ban unattended-upgrades curl
dpkg-reconfigure --priority=low unattended-upgrades   # enable

# SSH: key-only. PermitRootLogin prohibit-password = root may log in by SSH
# key but never by password.
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

# Firewall: only SSH, HTTP, HTTPS
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# fail2ban defaults are fine for SSH brute-force
systemctl enable --now fail2ban
```

## 2. Install Docker

```bash
# Docker official repo (apt's docker.io is older and we want compose v2)
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

## 3. DNS

In your registrar's DNS panel:

| Type | Host | Value           | TTL  |
|------|------|------------------|------|
| A    | @    | `<VPS IPv4>`    | 300  |
| A    | www  | `<VPS IPv4>`    | 300  |

Wait for propagation (`dig whatsupmissoula.com +short` should return your VPS IP).
Caddy won't be able to provision a cert until DNS resolves.

**If the domain is on Cloudflare, set the record to DNS-only (grey cloud),
not proxied (orange cloud).** Proxied, `dig` returns Cloudflare's IPs instead
of the VPS, Caddy's Let's Encrypt challenge can't validate against the origin,
and the browser gets a TLS / connection error. DNS-only points straight at the
VPS so Caddy issues its own cert. (Keeping the proxy is possible but needs a
Cloudflare Origin Certificate + SSL mode "Full (strict)" — out of scope here.)
Verify with the authoritative resolver, which skips local cache:
`dig +short whatsupmissoula.com @1.1.1.1` should equal `curl -s4 ifconfig.me`
on the VPS.

## 4. Clone + configure

```bash
mkdir -p /srv/wum
cd /srv/wum
git clone https://git.morse406.com/FractionalIT/WhatsUpMissoula.git .

# Secrets (host file, mode 600). docker-compose mounts this read-only into
# the pipeline container; Caddy reads WUM_DOMAIN / WUM_TLS_EMAIL from it.
cp .env.example .env
chmod 600 .env
nano .env   # fill IMAP_*, ANTHROPIC_API_KEY, WUM_DOMAIN, WUM_TLS_EMAIL

# Pipeline config (real stores list; gitignored).
cp pipeline/config.example.yaml pipeline/config.yaml
nano pipeline/config.yaml   # confirm stores list is current
```

## 5. Build + bring up Caddy

The pipeline container drops to a non-root user (uid 1000) so a bug or SSRF
in the weekly job can't touch the image. That user has to read the mounted
`.env`, which is mode 600 — so **`.env` must be owned by uid 1000 on the
host**, even though you operate as root. The same applies to the **`drops/`**
folder: the pipeline *moves* processed manual flyers into `drops/_archive/`,
so uid 1000 needs write access to the whole drops tree. These are the two
ownership changes the deploy needs.

```bash
cd /srv/wum

# Hand the 600 secret to uid 1000 so the in-container user can read it.
chown 1000:1000 .env
chmod 600 .env

# Manual-drop folder is a writable surface: the pipeline archives processed
# flyers into drops/_archive/, so uid 1000 must own the whole drops tree.
# (Uploads via SFTP land as root; the container still needs to move them.)
chown -R 1000:1000 drops

docker compose build pipeline    # builds the python + chromium image (~5 min first time)
docker compose up -d caddy       # starts Caddy; auto-issues TLS for WUM_DOMAIN

# Watch the cert handshake — should see "certificate obtained successfully"
docker compose logs -f caddy
```

Two traps worth knowing, both learned the hard way:

- **Don't `chown -R` the whole `/srv/wum`.** It would also re-own the hidden
  `.git` dir, and git (running as root) then refuses with "dubious ownership."
  Only the two writable surfaces need uid 1000 — `.env` and `drops/` — and you
  chown them individually (never the repo root). The rest of the repo stays
  owned by root; `config.yaml` and other tracked files are mode 644, readable
  by the container user as-is. (Symptom of a missed `drops/` chown: the weekly
  run renders the draft fine but crashes at the end with `PermissionError`
  moving the flyer into `drops/_archive/`.)
- **Never set `WUM_UID`/`WUM_GID` to 0.** The image defaults them to 1000
  (see `docker-compose.yml`), which matches the `.env` owner above, so you
  don't touch them at all. The build deliberately *refuses* uid/gid 0 —
  running the pipeline as root would defeat the non-root hardening. (An older
  version of this guide auto-wrote `WUM_UID=$(id -u)`; as root that's `0` and
  it breaks the build. It's gone now — don't reintroduce it.)

The first hit at `https://<domain>` will 404 (volume is empty until the first
publish). That's expected — Caddy is up, the site just hasn't been built yet.

## 6. First draft + publish

```bash
# Build the weekly draft (reads mailbox, fetches flyers, calls Claude, renders)
docker compose run --rm pipeline python run.py

# Eyeball the draft — it's in the wum_drafts volume; easiest way is to render
# it to a tmp dir on the host and scp / cat, or just trust the next step and
# promote, then iterate if it looks wrong.
docker compose run --rm pipeline python run.py --publish
```

After publish, `https://<domain>` serves the rendered site.

## 7. Weekly cron

Edit root's crontab (`crontab -e`) and add:

```cron
# Monday 06:00 — build the weekly draft. Publishing stays manual (review gate).
0 6 * * 1  cd /srv/wum && /usr/bin/docker compose run --rm pipeline python run.py >> /var/log/wum.log 2>&1
```

Then `touch /var/log/wum.log`.

Once you trust the output a few weeks running, fold publish into the cron:

```cron
0 6 * * 1  cd /srv/wum && /usr/bin/docker compose run --rm pipeline sh -c "python run.py && python run.py --publish" >> /var/log/wum.log 2>&1
```

## 8. Code updates

```bash
ssh root@<ip>
cd /srv/wum
git pull
docker compose build pipeline    # only if pipeline/ changed
docker compose restart caddy     # only if Caddyfile changed
```

The next cron tick (or a manual `docker compose run --rm pipeline …`) picks
up new code. Caddy keeps serving the existing site through the update.

Three different "updates" that are easy to confuse:
- **Pipeline code changed** (`pipeline/`, templates) → `docker compose build pipeline`.
  Templates are baked into the image, so a `git pull` alone is not enough.
- **Caddyfile changed** (CSP, headers, routing) → `docker compose restart caddy`.
  The Caddyfile is a bind mount, so no rebuild — just a config reload.
- **Caddy version update** (new Caddy release) → see below.

### Updating Caddy itself

The service is pinned to the floating `caddy:2-alpine` tag, so updating is just
pulling the newest 2.x image and recreating the container:

```bash
cd /srv/wum
docker compose pull caddy     # fetch the latest caddy:2-alpine
docker compose up -d caddy     # recreate the container on the new image
docker image prune -f          # optional: reclaim the old image layer
```

Safe and near-zero-downtime: TLS certs + the ACME account live in the
`caddy_data` volume (not the container), so an update never re-issues certs.
Only a sub-second blip while the container recreates. Run it whenever — a
monthly habit, or when you see a Caddy security release.

## 9. Backup

Two volumes hold state worth keeping:
- `caddy_data` — TLS account + issued certs. Losing it forces a fresh cert
  issuance on next start; Let's Encrypt has rate limits but you'd recover.
- `wum_site` — currently-published HTML. Losing it just shows a 404 until
  the next publish; not critical.

A weekly `docker run --rm -v wum_caddy_data:/data -v $(pwd):/backup alpine
tar czf /backup/caddy_data.tgz /data` snapshot is enough for the cert volume.
The pipeline output is rebuildable from the mailbox + AI on demand.

## 10. Operational notes

- **Logs:** `docker compose logs -f caddy` for the web server; `/var/log/wum.log`
  for the weekly job (or `docker compose logs pipeline` if you ran it ad hoc).
- **Disk usage:** Chromium images + Python deps take ~600 MB. Drafts + output
  are trivial. The cron job pulls flyer images via Claude vision — that's all
  in-memory, no disk growth.
- **Headless Chromium in containers:** pipeline/web_flyer.py already passes
  `--no-sandbox`, which is required when not running with user namespacing.
- **Manual flyer drop:** `docker compose run --rm -v ~/flyers:/flyers
  pipeline python run.py --images /flyers --store "Costco"`.
