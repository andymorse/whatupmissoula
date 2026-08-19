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
# Build the weekly draft (reads mailbox, fetches flyers, calls Claude, renders).
# --notify also emails the "draft ready" summary; drop it to render silently.
docker compose run --rm pipeline python run.py --notify

# Eyeball the draft — it's in the wum_drafts volume; easiest way is to render
# it to a tmp dir on the host and scp / cat, or just trust the next step and
# promote, then iterate if it looks wrong.
docker compose run --rm pipeline python run.py --publish
```

After publish, `https://<domain>` serves the rendered site.

## 7. Weekly schedule (systemd timer)

**Wednesday 08:00 Missoula time.** The run renders a DRAFT and emails you that
it's ready; publishing stays a manual step (the review gate).

The units live in the repo at `deploy/systemd/`, so they're version-controlled
rather than typed into `crontab -e` on the box:

```bash
cd /srv/wum
cp deploy/systemd/wum-weekly.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wum-weekly.timer

# Confirm when it will actually fire (shown in the box's local time = UTC)
systemctl list-timers wum-weekly.timer
```

Verify, watch, and run it by hand:

```bash
systemd-analyze calendar "Wed *-*-* 08:00:00 America/Denver"  # next few firings
journalctl -u wum-weekly.service -f                            # live log
journalctl -u wum-weekly.service -n 200 --no-pager             # last run
systemctl start wum-weekly.service                             # run now, off-schedule
```

### Why 08:00 Wednesday

Measured over 8 weeks of real mail, not guessed — arrival times in Mountain:

| Store | Lands |
|---|---|
| Good Food Store | Tue ~22:15 |
| Rosauers | Tue ~23:00 |
| Yoke's (both locations) | Wed ~06:05 |

08:00 clears the last arrival by about two hours. Albertsons comes from Flipp,
which posts the new ad Tuesday. **Don't move this earlier than ~07:00** or
Yoke's will start missing the window. Re-measure if a store changes its send
time — the query is in the git history for this section's commit.

### Why a timer instead of crontab

`OnCalendar` takes a timezone. The VPS clock is UTC, so a plain crontab line
would drift an hour every time Mountain flips between MDT and MST — the job
would quietly start running at 07:00 local each winter. systemd resolves the
zone at each firing (verified: 14:00 UTC in summer, 15:00 UTC after the
November change — both 08:00 Mountain). You also get `journalctl` instead of a
hand-rotated logfile, and `Persistent=true` catches a week the box was down.

The timezone suffix needs systemd ≥ 252 (Ubuntu 24.04 ships 255). On anything
older, fall back to crontab with an explicit `CRON_TZ`:

```cron
CRON_TZ=America/Denver
0 8 * * 3  cd /srv/wum && /usr/bin/docker compose run --rm pipeline python run.py --notify >> /var/log/wum.log 2>&1
```

### The review email

`--notify` sends a plain-text summary (`pipeline/notify.py`) over SMTP on the
same Gmail account the pipeline already reads with IMAP — no new secret, no new
dependency. It lists deals per store, flags stores that came back thin or
missing entirely (the tell for a broken fetcher), and prints the publish
command. Recipient is `REVIEW_NOTIFY_EMAIL` in `.env`, falling back to
`IMAP_USER` — set it to a personal address if you don't want the mailbox
emailing itself.

**Replying to it does nothing.** Approval-by-reply is Phase 2 in
[the automation plan](automation-and-civic-plan.md) and needs a nonce plus a
sender allowlist before it's safe to wire up.

### Publishing

```bash
cd /srv/wum && docker compose run --rm pipeline python run.py --publish
```

Folding `--publish` into the timer is deliberately **not** the next step — it
would put unreviewed AI output on the live site every week. Build Phase 2 first.

## 8. Code updates

```bash
ssh root@<ip>
cd /srv/wum
git pull
docker compose build pipeline    # only if pipeline/ changed
docker compose restart caddy     # only if Caddyfile changed
```
## 8b Code updates without re-reading the ads

Reuses the published deals verbatim (no email fetch, no vision pass) and
re-fetches the events section so the Roxy lineup stays current.

```
cd /srv/wum && git pull && docker compose build pipeline
docker compose run --rm pipeline python run.py --rerender
docker compose run --rm pipeline python run.py --publish
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
- **Manual flyer drop (one-shot, on the VPS):** `docker compose run --rm
  -v ~/flyers:/flyers pipeline python run.py --images /flyers --store "Costco"`.
- **Manual flyer drop (from your laptop):** `scripts/wum-drop <Store> <file…>`
  scp's a flyer into `/srv/wum/drops/<Store>/` for the next run to merge. It
  authenticates through the 1Password SSH agent, reads the VPS host from the
  `op` CLI (no hardcoded IP), and chowns the store folder to uid 1000 so the
  archive step doesn't hit the `drops/` PermissionError. See the header of
  `scripts/wum-drop` (or `wum-drop --help`) for one-time setup.
