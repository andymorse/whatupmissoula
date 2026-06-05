# What's Up Missoula

Weekly roundup of the best grocery deals across Missoula, MT. Each Monday an
offline "AI Job" reads the week's store flyers from a dedicated mailbox, has an
AI model pull out the real deals (item, price, normalized unit price), picks the
**best store of the week**, and publishes a clean static site.

A Fractional sub-brand — same look, logo, and palette as Fractional IT, just a
different name. For-fun project; no accounts, no payments, no tracking.

---

## Architecture (why it's built this way)

Security is the priority, so the public surface is **static HTML only** — no
database, no server-side runtime, nothing to inject into. Everything that holds
a secret (mailbox login, AI API key) lives in the **offline pipeline**, which
never faces the internet.

```
┌─ Monday "AI Job"  (pipeline/ — Python, holds all secrets) ──────────────┐
│  1. email_fetch    → read-only IMAP, find this week's flyer emails       │
│  2a. flyer stores  → web_flyer (headless Chromium) → vision (analyze)    │
│  2b. CHEF'STORE    → chefstore_fetch → parse embedded JSON → Deal objs   │
│  3. AI applies guidance + ai/watchlist.md picks, builds WeeklyReport     │
│  4. render         → Jinja2 templates → static HTML (a DRAFT)            │
│  5. (you review the draft)                                               │
│  6. publish        → promote draft → wum_site volume                     │
└──────────────────────────────────────────────────────────────────────────┘
                                  │ only static files cross over
                                  ▼
┌─ Public surface: Caddy serving static files (auto-TLS) ──────────────────┐
│  ports 80/443 only · TLS via Let's Encrypt · no app runtime · no secrets │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Static site, no Hugo (for now).** The pipeline already runs Python weekly,
  so it renders the deals pages directly with Jinja2 → flat HTML. One fewer
  dependency. Hugo is reserved for the future blog as its own section.
- **Pluggable AI.** `pipeline/providers/` defines a provider interface. We
  start on the Claude API (`claude.py`); a local model can drop in later
  (`local.py`) without touching the rest of the pipeline.
- **Two extraction paths, one report.** Flyer stores go through headless
  render + vision (`analyze.py`). CHEF'STORE bypasses vision entirely —
  their biweekly specials page embeds every product as structured JSON, so
  `chefstore_fetch.py` parses it directly. Both paths build the same
  `WeeklyReport` schema, render through the same templates.
- **Owner picks vs. AI picks.** `ai/watchlist.md` has two lists — `my_picks`
  (site owner's personal watch) and `ai_picks` (default household staples).
  When a deal matches a watchlist item, it gets a badge. Owner picks bubble
  into Top Steals with an "★ Editor's pick" callout to set the owner's
  curation apart from the AI's value ranking.
- **Bulk/wholesale is segregated.** CHEF'STORE is restaurant-supply (case
  packs, not units). Its `StoreWeek` carries `kind: "bulk_wholesale"` so the
  template badges it distinctly, and its deals are appended after `analyze()`
  — they never compete in "Top Steals" against household-scale grocery
  pricing.
- **Review before publish.** The job builds a draft; nothing goes live until
  you promote it. Guards against a misread price reaching the public site.

## Layout

```
ai/
  guidance.md             Standards doc that steers the AI (edit freely)
  watchlist.md            my_picks (owner) + ai_picks (default staples)
pipeline/                 The offline weekly job (Python)
  run.py                  Orchestrator — dispatches flyer vs. structured-JSON
  config.example.yaml     Stores, IMAP host, model, thresholds, paths
  schema.py               Deal / StoreWeek / WeeklyReport data models
  email_fetch.py          Read-only IMAP fetch (trigger + flyer link)
  web_flyer.py            Headless-Chromium render of a web flyer → image tiles
  extract.py              Normalize PDF/image attachments for the model
  analyze.py              Build prompt from guidance, call provider, parse
  chefstore_fetch.py      Structured-JSON path for CHEF'STORE (no vision)
  render.py               Jinja2 → static HTML draft
  publish.py              Promote draft → live
  providers/              Pluggable AI backends (base / claude / local)
  Dockerfile              Pipeline image — Python + Chromium + Poppler
site/
  templates/              Jinja2 templates (brand-styled)
  static/css/brand.css    Fractional design tokens + WUM styles
  static/img/             Logo and assets
docker-compose.yml        Caddy (long-running) + pipeline (one-shot)
Caddyfile                 TLS + static serve + security headers
docs/deploy.md            Step-by-step VPS runbook (Hetzner + Docker + Caddy)
```

## Status

**End-to-end works in production-shape.** Validated 2026-05-27 against the
live mailbox: real weekly ads from Good Food Store, Yoke's (Broadway +
Reserve), and Super 1 all flow cleanly through email_fetch → web_flyer →
vision → render. CHEF'STORE Missoula was added 2026-05-28 via the
structured-JSON path — 108 biweekly deals pulled with exact prices, zero
vision tokens.

```bash
# Default weekly path — fetches emails, dispatches each to its store's path
python pipeline/run.py

# A) Render an arbitrary web flyer page (testing)
python pipeline/run.py --url "https://orangestreetfoodfarm.com/weekly-ads/901" \
                       --store "Orange Street Food Farm"

# B) Manual drop — analyze flyer image(s)/PDF(s) you saved yourself.
#    Put files in a store-named subfolder (folder name = store), or pass a
#    single file with --store. Handy for Cloudflare-walled stores.
python pipeline/run.py --images ~/flyers          # ~/flyers/Costco/ad.pdf, etc.
python pipeline/run.py --images ad.png --store "Costco"

# C) Render the bundled sample report (no network/API needed — for UI work)
python pipeline/run.py --sample
```

Four input paths feed the same render chain:
- **email** (`email_fetch.py`) — the default weekly trigger. Finds flyer
  emails by known sender + flyer-ish subject, then dispatches each email to
  the right extraction path (flyer-render or structured-fetch).
- **web flyer** (`web_flyer.py`) — headless Chromium → vision. The main path
  for flyer stores, since most flyer emails link to a web-hosted ad.
- **structured JSON** (`chefstore_fetch.py`) — for stores whose specials
  page embeds the catalog as JSON (CHEF'STORE today). Skips vision entirely.
- **manual drop** (`--images`) — for stores we can't render (bot-walled) or
  one-offs.

## Stores in scope

Configured in `pipeline/config.yaml` under `stores:`. The store name there is
only a hint — the AI confirms the real store from the ad image itself
(except for the structured-JSON stores, where the source is unambiguous).

| Store | Path | Notes |
|---|---|---|
| Good Food Store | email → web flyer | Constant Contact → `goodfoodstore.com/sales-flyer/`. WordPress page exposes 3 full-res JPG pages + a PDF; the email anchor text is just "Click here", so `click here` is in `link_keywords`. **Runs a ~2-week ad but emails once**, so it's set `ad_period_days: 14` (see below) — otherwise the email ages out of the 8-day fetch window and the ad disappears in week 2. |
| Yoke's Fresh Market | email → web flyer | Mailchimp → `yokesfreshmarkets.com/weekly-ad/<location>`. **Two Missoula locations: Broadway + Reserve.** Yoke's signup form only allows one email per signup, so the mailbox uses two aliases (`whatupmissoula@`, `whatup2@`) — one subscribed to each location. Both emails arrive with identical sender, subject, and timestamp; Mailchimp encodes the store choice in the per-recipient `e=` token, which redirects to the correct `/broadway` or `/reserve` page. `email_fetch.py` keeps the most recent flyer email per `(store, To:)`, so both location ads come through — the `To:` is what distinguishes them. |
| Super 1 Foods | email → web flyer *(parked)* | **Parked 2026-06-05** — Stevensville + Hamilton are out of town; commented out in config to save run time/AI tokens. Re-enable by uncommenting the store block. Constant Contact → flyer redirect. Stevensville + Hamilton; AI reads location from the ad. Super 1 sometimes mixes formats — most weeks ship a normal "view the ad" link, but occasional one-offs (e.g. holiday promos) are inline-image emails with no link. The inline-image fallback ("Path B") is deferred until a second sample arrives. |
| CHEF'STORE | email → structured JSON | US Foods restaurant-supply chain. Email links to `chefstore.com/specials/` → location picker → biweekly hotsheet. The hotsheet's list view embeds every product as `productData` JSON; `chefstore_fetch.py` follows `/content/setStore/505/specials/` (Missoula = store #505), scrapes the Biweekly Specials tab URL, parses the inline JSON, and emits Deal objects directly. **Tagged `kind: bulk_wholesale`** — case-pack pricing, separate badge, excluded from Top Steals. Biweekly like Good Food Store, so it's also set `ad_period_days: 14` to survive into week 2. |
| Rosauers | email → (pending) | Mailchimp. Currently sending lifestyle/recipe emails ("425 Recipes with Brittany", "Summer Of Fruits") rather than a weekly ad — those get correctly dropped by the `subject_hints` whitelist. Investigation pending: whether Rosauers has a separate weekly-ad list. |
| Albertsons | n/a | Welcome email arrived 2026-05-21; no real weekly ad yet. |

**Multi-location rendering rule:** for stores with multiple Missoula locations
in scope (today: Yoke's; later: Super 1), the rendered output on the public
site must label each deal with its specific location (e.g. "Yoke's — Broadway"
vs "Yoke's — Reserve"). Missoula is small enough that locals will want to know
which store the price applies to. If a deal is identical at both locations,
combine them ("Yoke's — Broadway & Reserve") rather than dropping the label.
The location can be sourced reliably from the URL slug as a fallback to AI
extraction.

**Multi-week ad rule:** flyer emails are fetched in an IMAP `SINCE` window
(`email.lookback_days`, default 8). A store that emails **once for a multi-week
ad** (Good Food Store, CHEF'STORE) would age out of that window and vanish from
the site partway through its run. Setting `ad_period_days: N` on the store entry
keeps its most recent email "live" for `N` days (both are 14); the fetch widens
its search to the longest period and filters per store. Weekly stores need
nothing — they default to `lookback_days`. Note `pipeline/config.yaml` is
gitignored, so this lives in each host's config (mirrored in
`config.example.yaml`); the code change ships via git but the per-store value
must be set on the box.

## Watchlist (owner + AI picks)

`ai/watchlist.md` is the editable hint file that controls which deals get
"on your list" badges on the rendered page. Two lists:

- **`my_picks`** — the site owner's personal watch. Matches here render with
  a gold "★ on your list" badge inline and an "★ Editor's pick" callout in
  Top Steals. These bubble into Top Steals even when the AI's value ranking
  wouldn't have surfaced them, because owner curation is its own signal.
- **`ai_picks`** — default household staples (eggs, milk, butter, ground
  beef, etc.). Matches render with a quieter "★ pick" badge — the AI knows
  these are worth flagging without making them the headline.

Matching is liberal on item identity ("kombucha" matches GT's Synergy 16oz;
"eggs" matches "Grade A large, 1 dozen"). Parenthetical hints in the list
narrow but don't gate. CHEF'STORE deals don't get watchlist matching today —
the watchlist is household brands, the catalog is foodservice.

## Local dev

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt
cp .env.example .env                       # fill in secrets (never committed)
cp pipeline/config.example.yaml pipeline/config.yaml
python pipeline/run.py --sample            # render the bundled sample report
```

For full local runs against the live mailbox you also need `chromium` on
PATH (`apt install chromium` on Debian/Ubuntu) and `poppler-utils` for PDF
extraction (`apt install poppler-utils`). The Docker image has both baked
in — local dev is the only place you need to install them on the host.

## Deploying to a VPS

The full step-by-step runbook is in [`docs/deploy.md`](docs/deploy.md). Before
you start that, you (the human) need these things in hand — none are scripted
because they live outside the repo:

**Domain & DNS**
- [ ] Domain registered (default: `whatsupmissoula.com`)
- [ ] Email address you'll register with Let's Encrypt — ACME uses it for cert
      expiry notices and rate-limit recovery contact
- [ ] Access to the domain's DNS panel so you can point A records at the VPS

**VPS**
- [ ] Hetzner Cloud account (or another provider — runbook assumes Hetzner US)
- [ ] An SSH key pair on your laptop; public key ready to paste during VPS
      creation
- [ ] Decided which datacenter (Ashburn vs. Hillsboro for Hetzner US)

**Secrets to populate in `.env` on the VPS**
- [ ] `IMAP_USER` + `IMAP_APP_PASSWORD` — Google Workspace app password for the
      mailbox the flyer emails land in
- [ ] `ANTHROPIC_API_KEY` — for the Claude vision provider
- [ ] `WUM_DOMAIN` — public hostname Caddy will serve
- [ ] `WUM_TLS_EMAIL` — the Let's Encrypt contact email above

### Pre-flight order of operations on the VPS

`docs/deploy.md` has the canonical version with deeper rationale. The steps
below are enough to follow start-to-finish on their own.

**1. Spin up the VPS** at your provider. Ubuntu 24.04 LTS, US region (Hetzner
Ashburn or Hillsboro). Note the public IPv4 — you'll need it for DNS.

**2. Point DNS at the VPS** in your registrar's DNS panel:

| Type | Host | Value           | TTL |
|------|------|------------------|-----|
| A    | @    | `<VPS IPv4>`    | 300 |
| A    | www  | `<VPS IPv4>`    | 300 |

Wait for propagation — `dig <domain> +short` should return your VPS IP from
your laptop. **Caddy can't get a Let's Encrypt cert until DNS resolves**, and
ACME has rate limits on repeated failures, so don't bring Caddy up before
this resolves.

**3. Initial server setup.** SSH in as `root` (`ssh root@<ip>`) and do all
the steps below in one session. The goal: lock the box down and stand up a
non-root user (`wum`) that owns everything from here on — including the
docker socket, the repo, and `.env`.

  **3a. Update the system + enable auto-patches.**

  ```bash
  apt update && apt -y full-upgrade
  apt -y install ufw fail2ban unattended-upgrades curl
  dpkg-reconfigure --priority=low unattended-upgrades   # enable
  ```

  `unattended-upgrades` is what keeps the box safe between your visits — it
  pulls security patches automatically from here on.

  **3b. Create the non-root `wum` user — DO NOT SKIP THIS.**

  This is the user you'll log in as from now on. It will own `/opt/wum`,
  `.env`, and have docker access. Root SSH gets disabled in step 3c, so if
  you forget this step you'll lock yourself out of the box.

  ```bash
  # Create wum with sudo access (no password — SSH keys only).
  adduser --disabled-password --gecos "" wum
  usermod -aG sudo wum

  # Copy your SSH authorized_keys to wum so you can log in directly.
  mkdir -p /home/wum/.ssh
  cp ~/.ssh/authorized_keys /home/wum/.ssh/
  chown -R wum:wum /home/wum/.ssh
  chmod 700 /home/wum/.ssh
  chmod 600 /home/wum/.ssh/authorized_keys
  ```

  **Now, before doing anything else, open a SECOND terminal and verify SSH
  works as `wum`:**

  ```bash
  ssh wum@<ip>     # from your laptop — should let you in
  ```

  If that succeeds, you're safe to proceed. If it fails, **fix it now**
  before continuing — once you disable root login in 3c, this is your only
  way back in.

  **3c. Lock down SSH (no root login, no passwords).**

  ```bash
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/'        /etc/ssh/sshd_config
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
  systemctl reload ssh
  ```

  From here, only key-based logins are accepted and root can't SSH in at
  all. Keep your original root session open until you've verified wum SSH
  still works (see 3b warning).

  **3d. Firewall + fail2ban.**

  ```bash
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow OpenSSH         # SSH (port 22)
  ufw allow 80/tcp          # Caddy / Let's Encrypt ACME
  ufw allow 443/tcp         # Caddy HTTPS
  ufw --force enable

  systemctl enable --now fail2ban    # SSH brute-force protection
  ```

  **3e. Install Docker (with Compose v2).**

  ```bash
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker wum             # so wum can run `docker compose ...`
  ```

  The official install script ships Compose v2. Don't use apt's `docker.io`
  package — it's a much older version and doesn't include Compose.

  Note: members of the `docker` group are effectively root on this host
  (the docker socket lets a process mount `/` into a container). On a
  single-purpose box that's acceptable; just don't add unrelated users to
  this group later.

  **3f. Switch to wum for everything from here on.**

  ```bash
  exit            # leave the root session
  ssh wum@<ip>    # log back in as wum
  docker --version && docker compose version    # sanity check
  ```

  If `docker compose version` errors out, log out and back in once more —
  group membership only takes effect on a fresh shell.

**4. Clone the repo + fill secrets.** Now as the `wum` user:

```bash
sudo mkdir -p /opt/wum && sudo chown wum:wum /opt/wum
cd /opt/wum
git clone https://git.morse406.com/FractionalIT/WhatsUpMissoula.git .

cp .env.example .env
chmod 600 .env             # secrets stay readable only by wum
nano .env                  # fill IMAP_*, ANTHROPIC_API_KEY, WUM_DOMAIN, WUM_TLS_EMAIL

cp pipeline/config.example.yaml pipeline/config.yaml
nano pipeline/config.yaml  # confirm stores list matches what you want this week
```

**5. Build the pipeline image + bring up Caddy.**

```bash
docker compose build pipeline    # ~5 min first time (Python + Chromium + Poppler)
docker compose up -d caddy       # starts Caddy; auto-issues TLS for WUM_DOMAIN

# Watch the cert handshake — look for "certificate obtained successfully"
docker compose logs -f caddy
```

The first hit at `https://<domain>` will return 404 until step 7 — the
volume Caddy serves is empty until the first publish. That's expected.

**6. First weekly run** (builds a draft, doesn't publish):

```bash
docker compose run --rm pipeline python run.py
```

**7. Promote when the draft looks right:**

```bash
docker compose run --rm pipeline python run.py --publish
```

After this, `https://<domain>` serves the rendered site.

**8. Add the Monday-morning cron** so you don't have to remember. As `wum`,
`crontab -e` and add:

```cron
# Monday 06:00 — build the weekly draft. Publishing stays manual (review gate).
0 6 * * 1  cd /opt/wum && /usr/bin/docker compose run --rm pipeline python run.py >> /var/log/wum.log 2>&1
```

Then create the log file with the right ownership:

```bash
sudo touch /var/log/wum.log && sudo chown wum:wum /var/log/wum.log
```

Once you trust the output a few weeks running, fold publishing into the cron
(see `docs/deploy.md` §7 for that variant).

## Security notes

- Secrets live only in `.env` (gitignored), never in the repo or site output.
- The mailbox is accessed **read-only** via an app password.
- The internet-facing surface is Caddy serving static files only. The pipeline
  runs as a one-shot container, never reachable from the public internet.
- Caddy ships HSTS, X-Frame-Options DENY, and a CSP that allows only same-
  origin assets + Google Fonts. Tighten or relax in `Caddyfile`.
- See `docs/deploy.md` for the full hardening checklist (SSH key-only, ufw,
  fail2ban, unattended-upgrades).
