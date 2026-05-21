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
  email_fetch.py          Read-only IMAP fetch + attachment extraction
  extract.py              Normalize PDFs/images for the model
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

Scaffold + brand styling + AI guidance are in place. Email fetch / extract /
analyze / render are starting implementations to be validated against real
sample flyers (need: a few flyer emails in the mailbox + an Anthropic API key).

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
