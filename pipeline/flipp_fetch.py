"""Fetch a store's weekly ad from Flipp (Wishabi), the circular network behind
albertsons.com/weeklyad and friends.

Albertsons was the last store with no scrapeable source: its own weekly-ad page
is a store-gated SPA that never finishes rendering headless, so the ad reached
the site by hand — the owner downloaded a PDF and uploaded it to
`drops/Albertsons/` (see scripts/wum-drop). This module replaces that upload.

The ad itself isn't on albertsons.com at all. Albertsons publishes through
Flipp, whose backend is public, unauthenticated, and keyed by postal code:

  1. GET /flipp/flyers?locale=en-us&postal_code=<zip>
     → every flyer available in that zip, with merchant, name, valid_from /
       valid_to, and the flyer's storage `path` + `resolutions`.
  2. GET /flipp/flyers/<id>?locale=en-us&postal_code=<zip>
     → that flyer's `pages` (each page's left/right bounds) and its `items`.

Flipp stores a flyer as ONE wide canvas holding every page side by side
(Albertsons: 8442x2560 for 8 pages), cut into 256px tiles at six zoom levels:

    https://f.wishabi.net/<path><res_index>_<col>_<row>.jpg

So we download the tiles for the sharpest level, stitch the canvas, and slice it
back into per-page images using the `pages` bounds — then hand those to the same
image→vision path every other store uses.

**Why not use the `items` JSON?** It looks tempting (203 structured items with
exact prices) but it carries name/brand/price only — no regular price, no
category, no unit, no loyalty flag. Those are what drive percent_off and the Top
Steals grid, and vision reads them off the flyer art. Parsing items instead of
seeing the ad would quietly demote Albertsons out of Top Steals the way
CHEF'STORE is (deliberately) excluded. The tiles keep Albertsons a normal store.

Config (a store with `kind: flipp`):

    - name: "Albertsons"
      kind: "flipp"
      flipp_postal_code: "59801"   # required — Flipp keys everything off this
      flipp_merchant: "Albertsons" # optional; defaults to the store name
      flipp_flyer_name: "Weekly Ad"  # optional; prefer this over other circulars
      flipp_resolution: -2         # optional; see _resolution_index for the default
"""
from __future__ import annotations

import json
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from math import ceil
from pathlib import Path

from PIL import Image

from extract import to_flyer_images_pairs
from providers.base import FlyerImage
from url_guard import safe_url

API = "https://backflipp.wishabi.com/flipp"
CDN = "https://f.wishabi.net/"
TILE = 256          # Flipp's tile edge, in pixels, at every zoom level
TILE_WORKERS = 8    # a full-resolution flyer is a few hundred small GETs

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def fetch_flipp_flyers(store_cfg: dict, cfg: dict) -> list[FlyerImage]:
    """Find the store's current Flipp flyer, rebuild its pages, return tiles."""
    name = store_cfg.get("name", "Store")
    postal = str(store_cfg.get("flipp_postal_code") or "").strip()
    if not postal:
        raise RuntimeError(f"{name}: kind: flipp needs a flipp_postal_code in config")
    merchant = store_cfg.get("flipp_merchant") or name

    flyer = _pick_flyer(_list_flyers(postal), merchant,
                        store_cfg.get("flipp_flyer_name"), name)
    detail = _get_json(f"{API}/flyers/{flyer['id']}"
                       f"?locale=en-us&postal_code={urllib.parse.quote(postal)}")
    pages = sorted(detail.get("pages") or [], key=lambda p: p.get("page", 0))
    if not pages:
        raise RuntimeError(f"{name}: Flipp flyer {flyer['id']} reported no pages")

    # Same cap the PDF path applies, so a store can't blow the vision budget.
    max_pages = cfg.get("ai", {}).get("max_pages_per_flyer", 8)
    pages = pages[:max_pages]

    res_index = _resolution_index(flyer, store_cfg.get("flipp_resolution"))
    canvas = _build_canvas(flyer, res_index)
    scale = canvas.width / float(flyer["width"])

    with tempfile.TemporaryDirectory() as td:
        pairs: list[tuple[Path, str]] = []
        for pg in pages:
            box = (max(0, int(pg["left"] * scale)), 0,
                   min(canvas.width, int(pg["right"] * scale)), canvas.height)
            if box[2] - box[0] < 2:            # a zero-width panel isn't a page
                continue
            p = Path(td) / f"page_{pg.get('page', 0):02d}.jpg"
            canvas.crop(box).save(p, format="JPEG", quality=90)
            pairs.append((p, name))
        if not pairs:
            raise RuntimeError(f"{name}: Flipp flyer {flyer['id']} produced no page images")
        # Reuse the shared image→tile path (honours ai.image_max_px and the
        # tall-image slicing — these panels are much taller than they are wide).
        return to_flyer_images_pairs(pairs, cfg)


def _list_flyers(postal: str) -> list[dict]:
    url = f"{API}/flyers?locale=en-us&postal_code={urllib.parse.quote(postal)}"
    return _get_json(url).get("flyers") or []


def _pick_flyer(flyers: list[dict], merchant: str,
                prefer_name: str | None, store: str) -> dict:
    """Choose the store's current circular from everything Flipp lists for the zip.

    A merchant often runs several at once — Albertsons publishes both a weekly
    "Weekly Ad" and a month-long "Big Book of Savings". `flipp_flyer_name` picks
    the one we actually want; otherwise the most recently started wins.
    """
    mine = [f for f in flyers if (f.get("merchant") or "").strip().lower()
            == merchant.strip().lower()]
    if not mine:
        seen = sorted({f.get("merchant") or "?" for f in flyers})
        raise RuntimeError(
            f"{store}: no Flipp flyer for merchant {merchant!r}. "
            f"Merchants in this zip: {', '.join(seen) or '(none)'}"
        )
    if prefer_name:
        named = [f for f in mine
                 if prefer_name.strip().lower() in (f.get("name") or "").lower()]
        if named:
            mine = named
        else:
            print(f"  ! {store}: no Flipp flyer named like {prefer_name!r} — "
                  f"falling back to {', '.join(f.get('name') or '?' for f in mine)}")

    today = date.today()
    current = [f for f in mine
               if _day(f.get("valid_from")) <= today <= _day(f.get("valid_to"), high=True)]
    if not current:
        # Not fatal — the new ad sometimes posts a day early, and showing the ad
        # the store is actually publishing beats showing nothing.
        print(f"  ! {store}: no Flipp flyer valid today ({today}) — using the newest")
        current = mine
    return max(current, key=lambda f: _day(f.get("valid_from")))


def _resolution_index(flyer: dict, override) -> int:
    """Index into the flyer's `resolutions` list of divisors, coarsest first.

    Default is -2, the *second* sharpest level, not the sharpest. Flipp's
    full-size tiles (divisor 1.0) come back with the flyer's layers vertically
    displaced — price badges land on top of the numerals they belong to, and
    headline text double-prints. One level down renders cleanly, and it's still
    sharper than `ai.image_max_px`, so nothing is lost: a page arrives ~845x1652
    and stays a single vision tile instead of being sliced in two.

    Indices may be negative (Python-style) so a config value keeps its meaning
    if Flipp ever changes how many zoom levels it publishes.
    """
    res = flyer.get("resolutions") or [1.0]
    idx = -2 if override is None else int(override)
    if idx < 0:
        idx += len(res)
    if not 0 <= idx < len(res):
        raise RuntimeError(
            f"flipp_resolution {override} out of range for {len(res)} levels"
        )
    return idx


def _build_canvas(flyer: dict, res_index: int) -> Image.Image:
    """Download every tile at `res_index` and stitch the flyer's full canvas."""
    divisor = (flyer.get("resolutions") or [1.0])[res_index]
    width = max(1, int(round(flyer["width"] / divisor)))
    height = max(1, int(round(flyer["height"] / divisor)))
    cols, rows = ceil(width / TILE), ceil(height / TILE)
    path = (flyer.get("path") or "").lstrip("/")
    if not path:
        raise RuntimeError(f"Flipp flyer {flyer.get('id')} has no storage path")

    coords = [(c, r) for r in range(rows) for c in range(cols)]
    urls = [f"{CDN}{path}{res_index}_{c}_{r}.jpg" for c, r in coords]
    safe_url(urls[0])   # one DNS/scheme check — every tile is the same host

    with ThreadPoolExecutor(max_workers=TILE_WORKERS) as pool:
        blobs = list(pool.map(_get_tile, urls))

    # White ground: a missing edge tile leaves paper, not a black band.
    canvas = Image.new("RGB", (width, height), "white")
    got = 0
    for (c, r), blob in zip(coords, blobs):
        if not blob:
            continue
        try:
            canvas.paste(Image.open(blob).convert("RGB"), (c * TILE, r * TILE))
            got += 1
        except OSError:                     # a truncated/garbage tile
            continue
    if got < len(coords) * 0.5:
        raise RuntimeError(
            f"Flipp flyer {flyer.get('id')}: only {got}/{len(coords)} tiles "
            "downloaded — the CDN path or resolution index looks wrong"
        )
    return canvas


def _get_tile(url: str):
    """Fetch one tile, returning a BytesIO or None. Never raises — the caller
    tolerates gaps, and one flaky tile shouldn't sink the week's run."""
    import io

    try:
        return io.BytesIO(_get_bytes(url, timeout=20))
    except Exception:
        return None


def _day(value, high: bool = False) -> date:
    """Parse Flipp's ISO timestamps ("2026-08-19T00:00:00-04:00") to a date."""
    if not value:
        return date.max if high else date.min
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return date.max if high else date.min


def _get_json(url: str) -> dict:
    return json.loads(_get_bytes(url).decode("utf-8", "ignore"))


def _get_bytes(url: str, timeout: int = 30) -> bytes:
    safe_url(url)  # block file:// / internal-host SSRF before fetching
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


if __name__ == "__main__":
    # Smoke test: resolve the current flyer for each kind: flipp store (no API
    # key needed). Pass --tiles to also stitch + slice, printing the tile count.
    import sys

    from settings import load_config

    cfg = load_config()
    stores = [s for s in cfg.get("stores", []) if s.get("kind") == "flipp"]
    if not stores:
        print("No kind: flipp stores in config.")
    for sc in stores:
        print(f"\n{sc.get('name')}")
        postal = str(sc.get("flipp_postal_code") or "")
        print(f"  Zip:  {postal or '(missing flipp_postal_code)'}")
        try:
            f = _pick_flyer(_list_flyers(postal),
                            sc.get("flipp_merchant") or sc["name"],
                            sc.get("flipp_flyer_name"), sc["name"])
        except Exception as e:
            print(f"  Ad:   lookup failed — {type(e).__name__}: {e}")
            continue
        print(f"  Ad:   #{f['id']} {f.get('name')!r}  "
              f"{_day(f.get('valid_from'))} → {_day(f.get('valid_to'), high=True)}")
        print(f"  Size: {int(f['width'])}x{int(f['height'])}  "
              f"res levels: {len(f.get('resolutions') or [])}")
        if "--tiles" in sys.argv:
            print(f"  Tiles: {len(fetch_flipp_flyers(sc, cfg))}")
