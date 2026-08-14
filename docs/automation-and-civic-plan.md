# Plan: full automation, then the civic feed

Decided 2026-08-14. Written so the next session executes instead of re-planning.

**Order of work:** Phase 1 → 2 → 3. Don't start the civic feed until the
existing pipeline runs itself.

---

## Phase 1 — Automate what already exists

Goal: the weekly grocery run happens without the owner touching a terminal.

- [ ] Cron the weekly run for **late Wednesday morning** (ads land Wed AM).
      Runs the pipeline container with the existing command; produces a DRAFT
      only, exactly as today.
- [ ] Albertsons: agent (or scripted fetch) drops the PDF into
      `drops/Albertsons/` before the run, replacing the manual upload.
- [ ] Keep the draft→publish gate intact. Automation must NOT publish
      unreviewed output — Phase 2 is what makes hands-off publishing safe.

Blocking dependency: none. This can ship on its own.

---

## Phase 2 — Email review + approval

Goal: decouple the review gate from being at the machine. This is the unlock
that makes full automation safe, and it is reused by the civic feed.

**Key finding: no web framework needed.** `email_fetch.py` already does
read-only IMAP (`imaplib.IMAP4_SSL`, `IMAP_USER` / `IMAP_APP_PASSWORD`).
Sending is `smtplib` to the same Gmail account. Both stdlib — **no new deps**.

Rejected: click-to-approve links. Caddy is `root * /srv` + `file_server` with
no `reverse_proxy`; docker-compose runs only caddy + pipeline. Clickable
approval would need an app process, a Caddy route, token state, a CSP change,
and a write endpoint on the public internet. Not worth it to save a reply.

### Flow

1. Run finishes → items written as `status: pending`, nothing renders.
2. Pipeline sends **one** email: numbered items, `uncertain` ones flagged and
   sorted to the top, deep-links for spot-checking.
3. Owner replies from anywhere: `ok 1 2 4` / `all` / `no 3`. Keep the grammar
   dumb — this gets answered half-asleep.
4. Poll step reads the reply over IMAP, flips status, rerenders, publishes.

### Security

`From:` is spoofable and **DMARC is still an open item** (see
`project_security_review`). Guards:

- Single-use **nonce** per email; reply must quote it (reply-quoting makes this
  free for the owner, but an attacker must have read the message).
- Allowlist the sender address.
- Only accept approvals for items already in `pending`.

Blast radius if spoofed: a summary the pipeline already wrote goes live without
an eyeball. No text injection is possible through this path.

### Code delta

| Change | Notes |
|---|---|
| `pipeline/notify.py` | new, ~80 lines, SMTP send |
| `email_fetch.py` | add approval-reply reader; reuses existing IMAP connect |
| `run.py` | `--notify`, `--check-approvals` |
| data file | per-item `status` field |
| Caddyfile / docker-compose / requirements.txt | **untouched** |

### Open decision

Approval → live latency: **short poll cron (15–30 min)** — preferred, nearly
free, one more cron entry on the existing container — vs. picking it up on the
next scheduled run (simpler, but approval can sit for days).

---

## Phase 3 — The civic feed

Name: **TBD** — pick before building. Candidates so far: City Desk, The Docket,
Civic Beat, On the Agenda, Front Street.

### Editorial rules (owner's calls, already decided)

- **No jail, arrest, booking, or warrant data.** Dropped deliberately — wrong
  fit for the brand's voice.
- **All summaries are ours.** Do not reuse MCAT's or anyone else's writeups.
  Either the owner writes it or a model writes it under strict guidance.
- Every AI-written item passes the Phase 2 review gate before publishing.

### v1 scope

Meetings + what's being built. Two clean sources, no scraping:

1. **City meeting calendar RSS** (verified, 16 items, structured fields):
   `https://www.ci.missoula.mt.us/RSSFeed.aspx?ModID=58&CID=All-calendar.xml`
   Covers Council, Planning Commission, MRA, Police Commission, Health Board,
   Library Board, Bike/Ped, TPCC, Downtown BID, Housing Authority, and
   neighborhood councils. City news RSS: `ModID=1&CID=All-newsflash.xml`.
2. **New housing/permits** — city ArcGIS org `HfwHS0BxZBQ1E5DY`, public, no key:
   - `UDC_PermitData_v3_Points` — geocoded, IssueDate through 2026-06-01,
     Neighborhood / DwellingUnits / LandUseType. **Freshest layer; use this.**
   - `BuildingPermitDataAll` — 12,656 rows with Address / Work_Description /
     Business_Name / Project_Cost, but stale (max 2025-06-01). History only.
   - `PermitDataAll` — aggregate counts + revenue.

### v2 — transcripts and summaries

**Video is directly downloadable, no auth.** eScribe player page
`pub-missoula.escribemeetings.com/Players/ISIStandAlonePlayer.aspx?Id=<meetingId>`
exposes `data-client_id="missoula"` and `data-file_name="X.mp4"`, resolving to:

```
https://video.isilive.ca/missoula/<file>.mp4
```

Verified: HTTP 200, `video/mp4`, 349,485,867 bytes, range requests supported.
eScribe also indexes video **by agenda item** (`video.Bookmarks[i].AgendaItemId`)
— that's how summary lines deep-link to the exact moment.

Note: `pub-missoula.escribemeetings.com` returns **403 to plain HTTP clients**;
needs a browser UA or the existing Playwright/chromium path.

**Transcription: Deepgram, fetched by URL.** The 349 MB file never touches the
VPS — Deepgram pulls it itself:

```
POST https://api.deepgram.com/v1/listen
  ?model=nova-3&smart_format=true&diarize=true&paragraphs=true&utterances=true
  {"url": "https://video.isilive.ca/missoula/<file>.mp4"}
```

- `diarize` gives `Speaker 0/1/2`, **not names** — mapping to council members
  needs the agenda roster, or don't claim attribution.
- `utterances` gives the timestamps that drive video deep-links.
- Use the async `callback=` pattern for 2h+ files.

**Two-stage summarization** (cheap *and* accurate):

- Stage 1 — **Haiku 4.5, batched**: 30K-token transcript → structured JSON
  (agenda items, timestamps, decisions, vote tallies, quotes). ~$0.019.
- Stage 2 — **Sonnet 5**: reads only the ~3K-token structured output → WUM-voice
  prose. ~$0.03 batched. The expensive model never sees the raw transcript.

The structured intermediate is what the site needs anyway for per-item links.

### Costs (verified 2026-08-14)

Per 2h15m meeting ≈ 135 min audio ≈ 30K-token transcript:

| Item | Cost |
|---|---|
| Deepgram nova-3 batch ($0.0043/min) | $0.58 |
| Haiku 4.5 (30K in / 1.5K out) | $0.038 → $0.019 batched |
| Sonnet 5 | $0.113 → $0.056 batched |
| Opus 5 | $0.188 → $0.094 batched |

At ~3 meetings/week (~6h audio): **Deepgram ~$6.70/mo**, Claude **$0.25–$2.44/mo**.
Transcription is 3–30× the model cost — **the model choice is not the cost lever.**
Deepgram gives $200 free credit (~775 hours) to start.

### API notes

- **Batch API** is a flat 50% off and fits perfectly (weekly, not
  latency-sensitive). Already priced in above.
- **Caching gotcha:** minimum cacheable prefix is **4096 tokens on Haiku 4.5**
  (vs 1024 on Sonnet 5). A guidance doc the size of `ai/guidance.md` (~2.5K
  tokens) sits *below* Haiku's floor and **silently won't cache** —
  `cache_creation_input_tokens: 0`, no error.
- Use **structured outputs** (`output_config.format` + JSON schema) rather than
  the `"Output ONLY valid JSON"` prose instruction. Hard guarantee, and worth
  retrofitting into the grocery provider too.

### Guidance doc (`ai/civic_guidance.md`)

Mirrors `ai/guidance.md`, cached the same way:

- Every claim traces to a transcript span; emit the timestamp with it.
- Never state a vote tally or dollar figure not spoken aloud.
- Speaker attribution only where diarization + roster agree; otherwise
  "a council member".
- Report what happened, not whether it was good. No editorializing.
- Per-item `uncertain: true` so shaky items surface first in the review email.

### Deferred / researched, not v1

- **Council agendas + packets** (eScribe) — needs Playwright. v2.
- **Weekly permit activity report** — Archive Center `AMID=191`, updated weekly
  with addresses/descriptions/values. Also `AMID=57` (monthly, back to 2010),
  `AMID=228` (quarterly). JS-driven listing.
- **EngageMissoula** `engagemissoula.com/development-applications` — active
  rezonings/subdivisions with open comment periods.
- **County commissioners** — 2pm 1st/2nd/4th Thu; CivicClerk; standard API
  endpoints 404, but they offer email agenda subscriptions.
- **MCPS school board** — 2nd/4th Tue 5pm; Diligent Community. Target Range
  uses BoardDocs (much friendlier).
- **Restaurant inspections** — `inspectionsonline.us/MT/missoulamissoula/Inspect.nsf`
  (Lotus Domino, POST search). Their own text: "All inspection reports are
  public record."
- **Liquor licenses** — **no public feed exists.** Transfers require public
  notice + 30-day protest (MCA 16-4-204); DOR publishes available licenses 4
  weeks in a local paper. Only realistic capture: legal notices
  (`montanapublicnotices.com/mna/legals/`) or agenda items. Possibly never
  more than a scrape. A records request to DOR ABC (406-444-6900) would settle
  whether they'll provide a recurring list.

### Prior art

- `montanablotter.com` — aggregates 15 MT source pages incl. Missoula County.
- `citizenportal.ai` — AI-summarizes Missoula County commission meetings.

Neither is Missoula-first or written in a local voice. That's the opening.

### MCAT

Missoula Community Access Television records city, county, **and** school
district meetings; mirrored to Internet Archive (`collection:mcatcollection`,
12,019 items, ~3-day lag, full JSON API). We are **not** using their summaries.
They're a local nonprofit doing the production work — if we lean on their feed
at all, talk to them first and credit them. Linking/embedding is fine.
