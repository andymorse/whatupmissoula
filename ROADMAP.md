# Roadmap

Where What's Up Missoula is headed. This is a living document — it's just a
markdown file in the repo, so edit it like any other file and commit.

**How to add an item:** pick the section that matches how soon it's happening
(**Now** / **Next** / **Later**), add a checkbox line, and keep it to one
sentence. Tick the box (`- [x]`) when it ships, or move it to
[Shipped](#shipped). Use *(parked)* and a date for anything intentionally on
hold. Link to an issue or a doc if there's more detail.

```
- [ ] Short description of the thing — one line of why/context.
```

---

## Now
*Actively being worked or next up.*

- [ ] **Cron automation** — move off manual runs to a scheduled weekly job.
  Schedule for **Wednesday morning** — that's when the store ads land in the
  mailbox. Currently run by hand on Wednesday. Phase 1 of
  [the automation + civic plan](docs/automation-and-civic-plan.md).
- [ ] **Email review + approval** — pipeline emails the draft; reply `ok 1 2 4`
  to publish. No web backend needed (reuses the existing IMAP plumbing). This
  is what makes hands-off automation safe. Phase 2 of the plan above.

## Next
*Decided, not started.*

- [ ] **Grocery list builder (phase 2)** — checkbox each deal → grouped
  by-store list with email/export. *(parked 2026-06-06; open question is the
  email mechanism — `mailto:` vs a small backend.)*
- [ ] **1st party ads** — Build pipe line
- [ ] **SEO** - For Google, Kagi, and AI
- [ ] **Civic feed (name TBD)** — meetings, agendas, and what's being built, in
  a WUM voice. Sources verified, costs priced, transcript pipeline designed in
  [the plan](docs/automation-and-civic-plan.md). Blocked on Phases 1–2. **Pick
  a name first** — candidates: City Desk, The Docket, Civic Beat, On the
  Agenda, Front Street.

## Later
*Ideas worth keeping; not committed.*

- [ ] **Inline-image promo support ("Path B")** — handle email flyers that ship
  as an inline image with no "view the ad" link. *(deferred until a second
  inline-only sample shows up.)*
- [ ] **Deal filtering (e.g. organic only)** — client-side, CSS-only toggle to
  stay within the static/no-backend model. Needs the organic tag first, and is
  gated behind the broader UI pass.
- [ ] **Price history** — track item prices over time to show value trends and
  spot whether a "deal" is actually a good price.
- [ ] **Blog section** — the reserved Hugo section for longer writeups.
- [ ] **Local sports scores page** — embed [ScoreStream](https://scorestream.com)
  widgets on a dedicated page for live/updated scores of Missoula-area teams
  (preps + college); first step toward broadening past grocery into local
  content.
- [ ] **Build in intellegent search** — embed

---

## Shipped
*Newest first.*

- [x] Albertsons auto-fetch — the ad is pulled from Flipp every run
  (`kind: flipp`), replacing the manual PDF upload. Phase 1 of the automation
  plan; no store needs a manual drop any more.
- [x] Two-tier badging — Editor's Pick (gold) + WUM Pick (navy).
- [x] Per-location deal labeling for multi-store chains (Yoke's, Super 1).
- [x] Top Steals grid with seasonal weighting.

---

## Ideas inbox
*Unsorted suggestions (e.g. from the network) — triage into a section above.*

-
