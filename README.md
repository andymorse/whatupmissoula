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
┌─ Monday "AI Job"  (pipeline/ — Python, holds all secrets) ───────────┐
│  1. email_fetch  → read-only IMAP, pull this week's flyer attachments │
│  2. extract      → PDFs / images → model-ready inputs                 │
│  3. analyze      → prompt = ai/guidance.md + flyers → structured deals │
│  4. render       → Jinja2 templates → static HTML (a DRAFT)           │
│  5. (you review the draft)                                            │
│  6. publish      → promote draft → live web root                      │
└────────────────────────────────────────────────────────────────────────┘
                              │ only static files cross over
                              ▼
┌─ Public VPS: Nginx serving static files ────────────────────────────┐
│  ports 80/443 only · TLS · no app runtime · no secrets present       │
└────────────────────────────────────────────────────────────────────────┘
```

- **Static site, no Hugo (for now).** The pipeline already runs Python weekly,
  so it renders the deals pages directly with Jinja2 → flat HTML. One fewer
  dependency. Hugo is reserved for the future blog as its own section.
- **Pluggable AI.** `pipeline/providers/` defines a provider interface. We start
  on the Claude API (`claude.py`); a local model can drop in later (`local.py`)
  without touching the rest of the pipeline.
- **Review before publish.** The job builds a draft; nothing goes live until you
  promote it. Guards against a misread price reaching the public site.

## Layout

```
ai/guidance.md            The standards doc that steers the AI (edit freely)
pipeline/                 The offline weekly job (Python)
  run.py                  Orchestrator
  config.example.yaml     Stores, IMAP host, model, thresholds, paths
  schema.py               Deal / StoreWeek / WeeklyReport data models
  email_fetch.py          Read-only IMAP fetch (trigger + flyer link)
  web_flyer.py            Headless-Chromium render of a web flyer → image tiles
  extract.py              Normalize PDF/image attachments for the model
  analyze.py              Build prompt from guidance, call provider, parse
  render.py               Jinja2 → static HTML draft
  publish.py              Promote draft → live
  providers/              Pluggable AI backends (base / claude / local)
site/
  templates/              Jinja2 templates (brand-styled)
  static/css/brand.css    Fractional design tokens + WUM styles
  static/img/             Logo and assets
docs/deploy.md            VPS hardening, cron, Nginx (deployment phase)
```

## Status

**End-to-end works.** Verified against a real web flyer (Orange Street Food
Farm): headless Chromium renders the JS-based weekly-ad page, the image is
sliced into tiles, Claude extracts ~40 deals with accurate prices + normalized
unit prices, and the branded static site builds. Try it:

```bash
# A) Render a web flyer page
python pipeline/run.py --url "https://orangestreetfoodfarm.com/weekly-ads/901" \
                       --store "Orange Street Food Farm"

# B) Manual drop — analyze flyer image(s)/PDF(s) you saved yourself.
#    Put files in a store-named subfolder (folder name = store), or pass a
#    single file with --store. Handy for Cloudflare-walled stores (e.g. Costco).
python pipeline/run.py --images ~/flyers          # ~/flyers/Costco/ad.pdf, etc.
python pipeline/run.py --images ad.png --store "Costco"
```

Three input paths feed the same analyze→render chain:
- **web flyer** (`web_flyer.py`) — headless render → vision; the main path, since
  most flyers (even the "email" stores) link to a web-hosted ad.
- **manual drop** (`--images`) — for stores we can't render (bot-walled) or one-offs.
- **email** (`email_fetch.py`) — the default weekly path: find flyer emails (known
  store sender + flyer-ish subject), pull the "view the ad" link from the HTML, and
  render it via `web_flyer`. Validated 2026-05-27 against the live mailbox — real
  weekly ads from GFS, Yoke's (Broadway + Reserve), and Super 1 all flow cleanly.
  Just run `python pipeline/run.py`.

## Stores in scope

Configured in `pipeline/config.yaml` under `stores:`. The store name there is
only a hint — the AI confirms the real store from the ad image itself.

| Store | Email path | Notes |
|---|---|---|
| Good Food Store | Constant Contact → `goodfoodstore.com/sales-flyer/` | WordPress page exposes 3 full-res JPG pages + a PDF; the email anchor text is just "Click here", so `click here` is in `link_keywords`. |
| Yoke's Fresh Market | Mailchimp → `yokesfreshmarkets.com/weekly-ad/<location>` | **Two Missoula locations: Broadway + Reserve.** Yoke's signup form only allows one email per signup, so the mailbox uses two aliases (`whatupmissoula@`, `whatup2@`) — one subscribed to each location. Both emails arrive with identical sender, subject, and timestamp; Mailchimp encodes the store choice in the per-recipient `e=` token, which redirects to the correct `/broadway` or `/reserve` page. `email_fetch.py` dedups on `(sender, subject, To:)` so both location ads come through. |
| Super 1 Foods | Constant Contact → flyer redirect | Stevensville + Hamilton; AI reads location from the ad. Note: Super 1 sometimes mixes formats — most weeks ship a normal "view the ad" link, but occasional one-offs (e.g. holiday promos) are inline-image emails with no link. The inline-image fallback ("Path B") is deferred until a second sample arrives — see `~/.claude/projects/-root-whatsupmissoula/memory/project_email_inline_images.md`. |
| Rosauers | Mailchimp | Currently sending lifestyle/recipe emails ("425 Recipes with Brittany", "Summer Of Fruits") rather than a weekly ad — those get correctly dropped by the `subject_hints` whitelist. Investigation pending: whether Rosauers has a separate weekly-ad list. |
| Albertsons | n/a | Welcome email arrived 2026-05-21; no real weekly ad yet. |

**Multi-location rendering rule:** for stores with multiple Missoula locations
in scope (today: Yoke's; later: Super 1), the rendered output on the public
site must label each deal with its specific location (e.g. "Yoke's — Broadway"
vs "Yoke's — Reserve"). Missoula is small enough that locals will want to know
which store the price applies to. If a deal is identical at both locations,
combine them ("Yoke's — Broadway & Reserve") rather than dropping the label.
The location can be sourced reliably from the URL slug as a fallback to AI
extraction.

**Extra dependency:** the `chromium` binary must be on PATH (`apt install chromium`).

## Local dev

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt
cp .env.example .env                       # fill in secrets (never committed)
cp pipeline/config.example.yaml pipeline/config.yaml
python pipeline/run.py --dry-run           # once implemented
```

## Security notes

- Secrets live only in `.env` (gitignored), never in the repo or site output.
- The mailbox is accessed **read-only** via an app password.
- The internet-facing box serves static files only; the pipeline runs elsewhere
  or as an isolated non-web user. See `docs/deploy.md`.
