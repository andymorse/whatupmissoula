# Manual flyer drops

Hand-uploaded ad files (PDFs or images) for stores with **no scrapeable ad
source**.

No store needs this right now — Albertsons was the last one, and it's now
fetched automatically from Flipp (`pipeline/flipp_fetch.py`). The folder stays
as the fallback: if a fetcher breaks mid-week, dropping the PDF in here still
gets the ad on the site, and it's the quickest way to onboard a new store with
no feed at all.

## How it works

Put files in a **subfolder named after the store**. The subfolder name becomes
the store label on the site:

```
drops/
  Albertsons/
    weekly-ad.pdf      ← drop the downloaded PDF here
```

The next normal pipeline run (`docker compose run --rm pipeline python run.py`)
merges everything here alongside the emailed/web flyers, then **moves processed
files to `drops/_archive/<week>/`** so they don't repeat next week.

Notes:
- PDFs and images both work; PDF pages are rasterized automatically.
- Files dropped at the top level (not in a store subfolder) use the filename as
  the store label — prefer subfolders for clean names.
- `_archive/` is ignored by the scanner.
- The uploaded files themselves are git-ignored (only this folder skeleton is
  tracked).
