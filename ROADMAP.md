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
  mailbox. Currently run by hand.

## Next
*Decided, not started.*

- [ ] **Grocery list builder (phase 2)** — checkbox each deal → grouped
  by-store list with email/export. *(parked 2026-06-06; open question is the
  email mechanism — `mailto:` vs a small backend.)*
- [ ] **Albertsons deals source** — no scrapeable flyer (store-gated SPA), so
  bring it in via the email mailbox or manual `--images`.
- [ ] **Organic tag** — flag deals as organic (data + badge) so it's clear at a
  glance; surfaces whether any Top Steals are organic. Data groundwork for
  filtering later.

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

---

## Shipped
*Newest first.*

- [x] Two-tier badging — Editor's Pick (gold) + WUM Pick (navy).
- [x] Per-location deal labeling for multi-store chains (Yoke's, Super 1).
- [x] Top Steals grid with seasonal weighting.

---

## Ideas inbox
*Unsorted suggestions (e.g. from the network) — triage into a section above.*

-
