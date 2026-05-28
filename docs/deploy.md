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

```bash
# Patch + auto-updates
apt update && apt -y full-upgrade
apt -y install ufw fail2ban unattended-upgrades curl
dpkg-reconfigure --priority=low unattended-upgrades   # enable

# Non-root user with sudo + docker (added in step 2)
adduser --disabled-password --gecos "" wum
usermod -aG sudo wum
mkdir -p /home/wum/.ssh
cp ~/.ssh/authorized_keys /home/wum/.ssh/
chown -R wum:wum /home/wum/.ssh
chmod 700 /home/wum/.ssh && chmod 600 /home/wum/.ssh/authorized_keys

# SSH: key-only, no root login
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
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

From here on, log in as `wum` (`ssh wum@<ip>`).

## 2. Install Docker

```bash
# Docker official repo (apt's docker.io is older and we want compose v2)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker wum
# Log out + back in so the group takes effect, then:
docker --version && docker compose version
```

Note: membership in the `docker` group is effectively root on this host
(the docker socket lets you mount `/`). On a single-purpose box that's
acceptable; just don't add unrelated users to it.

## 3. DNS

In your registrar's DNS panel:

| Type | Host | Value           | TTL  |
|------|------|------------------|------|
| A    | @    | `<VPS IPv4>`    | 300  |
| A    | www  | `<VPS IPv4>`    | 300  |

Wait for propagation (`dig whatsupmissoula.com +short` should return your VPS IP).
Caddy won't be able to provision a cert until DNS resolves.

## 4. Clone + configure

```bash
sudo mkdir -p /opt/wum && sudo chown wum:wum /opt/wum
cd /opt/wum
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

```bash
cd /opt/wum

# If host wum isn't UID 1000, set WUM_UID/WUM_GID in .env before building.
# The pipeline image bakes the user IDs in so the mounted .env is readable.
test "$(id -u)" = 1000 || echo "WUM_UID=$(id -u)" >> .env
test "$(id -g)" = 1000 || echo "WUM_GID=$(id -g)" >> .env

docker compose build pipeline    # builds the python + chromium image (~5 min first time)
docker compose up -d caddy       # starts Caddy; auto-issues TLS for WUM_DOMAIN

# Watch the cert handshake — should see "certificate obtained successfully"
docker compose logs -f caddy
```

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

Edit `wum`'s crontab (`crontab -e`) and add:

```cron
# Monday 06:00 — build the weekly draft. Publishing stays manual (review gate).
0 6 * * 1  cd /opt/wum && /usr/bin/docker compose run --rm pipeline python run.py >> /var/log/wum.log 2>&1
```

Then `sudo touch /var/log/wum.log && sudo chown wum:wum /var/log/wum.log`.

Once you trust the output a few weeks running, fold publish into the cron:

```cron
0 6 * * 1  cd /opt/wum && /usr/bin/docker compose run --rm pipeline sh -c "python run.py && python run.py --publish" >> /var/log/wum.log 2>&1
```

## 8. Code updates

```bash
ssh wum@<ip>
cd /opt/wum
git pull
docker compose build pipeline    # only if pipeline/ changed
docker compose restart caddy     # only if Caddyfile changed
```

The next cron tick (or a manual `docker compose run --rm pipeline …`) picks
up new code. Caddy keeps serving the existing site through the update.

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
