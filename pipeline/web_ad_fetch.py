"""Fetch a store's weekly ad when it's a web-hosted image flyer on a ShopHero site.

Some stores publish their weekly ad as a full-page JPG on a ShopHero-powered
storefront (Nuxt/Vue), not as an emailed flyer or a PDF. Orange Street Food Farm
is the first: the ad lives at `…/weekly-ads/<ad_id>` and the page is *server*-
rendered, so the page image URL and the printed date range are right there in the
HTML — no headless browser needed.

Two wrinkles this module handles:

  • The ad id is NOT a stable +1 each week. Observed: id 904 = May 27–Jun 2,
    id 906 = Jun 3–9 (905 is an empty placeholder, 907 500s). So we can't just
    increment. Instead we scan a small window of ids forward from the last one
    we resolved, read each page's printed date range, and pick the ad whose range
    covers today. The resolved id is cached so next week's scan stays short.

  • A multi-page ad renders every page's <img> server-side (the site's `unlazy`
    module runs during SSR — unlike Good Food Store, whose previews lazy-load
    client-side and defeated a screenshot). So a plain GET gets the whole ad; we
    pull all `ad_<id>_page_<n>_<hash>.jpg` URLs and feed them to the shared
    image→vision path.

Config (a store with `kind: web_ad`):

    - name: "Orange Street Food Farm"
      kind: "web_ad"
      weekly_ad_url: "https://www.orangestreetfoodfarm.com/weekly-ads"  # base; /<id> appended
      ad_seed_id: 906        # a known-good ad id to start scanning from
      scan_window: 8         # ids to probe forward from the last resolved (optional)
"""
from __future__ import annotations

import html as htmllib
import json
import re
import tempfile
import urllib.request
from datetime import date, datetime
from pathlib import Path

from extract import to_flyer_images_pairs
from providers.base import FlyerImage
from url_guard import safe_url

# The ShopHero CDN serves the flyer as AVIF (the signed URL bakes in f=auto and
# ignores Accept). Importing this registers an AVIF opener with Pillow so the
# shared extract path can read it. Soft import: a clear error surfaces at open
# time if the dep is missing (see requirements.txt).
try:
    import pillow_avif  # noqa: F401
except ImportError:
    pass

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "state"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# "Jun 3, 2026 - Jun 9, 2026" — the ad's printed valid range.
_DATE_RANGE_RE = re.compile(
    r"([A-Z][a-z]{2} \d{1,2}, \d{4})\s*-\s*([A-Z][a-z]{2} \d{1,2}, \d{4})"
)
# Full URL of an ad page image: …/ad_<adId>_page_<n>_<hash>.jpg
_AD_IMG_RE = re.compile(
    r"https?://[^\s\"'<>]+/ad_\d+_page_(\d+)_[a-z0-9]+\.jpg", re.I
)
# The image host usually 302s to a signed CDN URL, but sometimes answers with a
# tiny <meta http-equiv=refresh> HTML page instead; this pulls the target out.
_META_REFRESH_RE = re.compile(r"url=['\"]?(https?://[^'\"> ]+)", re.I)


def fetch_web_ad_flyers(store_cfg: dict, cfg: dict) -> list[FlyerImage]:
    """Resolve the current web ad, download its page image(s), return vision tiles."""
    name = store_cfg.get("name", "Store")
    base_url = store_cfg.get("weekly_ad_url")
    if not base_url:
        raise RuntimeError(f"{name}: kind: web_ad needs a weekly_ad_url in config")
    seed = int(store_cfg.get("ad_seed_id", 0))
    window = int(store_cfg.get("scan_window", 8))

    start = max(seed, _load_last_id(name))
    ad = _resolve_current_ad(base_url, start, window, date.today())
    if not ad:
        raise RuntimeError(
            f"{name}: no current weekly ad found scanning ids {start}..{start + window} "
            f"on {base_url} (is ad_seed_id stale?)"
        )
    _save_last_id(name, ad["id"])

    with tempfile.TemporaryDirectory() as td:
        pairs: list[tuple[Path, str]] = []
        for i, img_url in enumerate(ad["images"]):
            p = Path(td) / f"page_{i}.img"
            p.write_bytes(_get_image_bytes(img_url))
            pairs.append((p, name))
        # Reuse the shared image→tile path (honours ai.image_max_px, tall-image
        # slicing). The printed date range is also parsed by the vision step from
        # the flyer itself into valid_from / valid_through.
        return to_flyer_images_pairs(pairs, cfg)


def _resolve_current_ad(base_url: str, start_id: int, window: int,
                        today: date) -> dict | None:
    """Scan ids [start_id .. start_id+window] and pick the ad covering today.

    Falls back to the most recently *started* ad if none strictly covers today
    (e.g. the new week's ad isn't published yet), so the site keeps showing the
    latest rather than nothing.
    """
    ads = [a for a in (_probe_ad(base_url, i)
                       for i in range(start_id, start_id + window + 1)) if a]
    if not ads:
        return None
    covering = [a for a in ads if a["from"] <= today <= a["through"]]
    if covering:
        return max(covering, key=lambda a: a["from"])
    started = [a for a in ads if a["from"] <= today]
    if started:
        return max(started, key=lambda a: a["from"])
    return min(ads, key=lambda a: a["from"])   # nothing started yet → soonest


def _probe_ad(base_url: str, ad_id: int) -> dict | None:
    """Fetch one ad page; return its id/date range/image urls, or None if empty.

    Returns None for placeholder ids (200 but no date/images) and for ids that
    error (some future ids 500 until published).
    """
    try:
        html = _get(f"{base_url.rstrip('/')}/{ad_id}")
    except Exception:
        return None
    rng = _DATE_RANGE_RE.search(html)
    if not rng:
        return None
    imgs = _ad_image_urls(html)
    if not imgs:
        return None
    try:
        valid_from = datetime.strptime(rng.group(1), "%b %d, %Y").date()
        valid_through = datetime.strptime(rng.group(2), "%b %d, %Y").date()
    except ValueError:
        return None
    return {"id": ad_id, "from": valid_from, "through": valid_through, "images": imgs}


def _ad_image_urls(html: str) -> list[str]:
    """All distinct ad page image URLs, ordered by page number."""
    seen: dict[str, int] = {}
    for m in _AD_IMG_RE.finditer(html):
        seen.setdefault(m.group(0), int(m.group(1)))
    return sorted(seen, key=seen.get)


def _load_last_id(name: str) -> int:
    try:
        return int(json.loads((STATE_DIR / "web_ad.json").read_text()).get(name, 0))
    except (FileNotFoundError, ValueError, KeyError):
        return 0


def _save_last_id(name: str, ad_id: int) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / "web_ad.json"
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        data = {}
    data[name] = ad_id
    path.write_text(json.dumps(data, indent=2))


def _get_image_bytes(url: str) -> bytes:
    """Download an ad image, following the host's occasional meta-refresh page."""
    data = _get_bytes(url)
    head = data[:200].lstrip().lower()
    if head.startswith((b"<!doctype", b"<html")):
        m = _META_REFRESH_RE.search(data.decode("utf-8", "ignore"))
        if m:
            data = _get_bytes(htmllib.unescape(m.group(1)))
    return data


def _get(url: str) -> str:
    return _get_bytes(url).decode("utf-8", "ignore")


def _get_bytes(url: str) -> bytes:
    safe_url(url)  # block file:// / internal-host SSRF before fetching
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


if __name__ == "__main__":
    # Smoke test: resolve the current ad for each kind: web_ad store (no API key
    # needed). Pass --tiles to also download + rasterize, printing the tile count.
    import sys

    from settings import load_config

    cfg = load_config()
    web_ad = [s for s in cfg.get("stores", []) if s.get("kind") == "web_ad"]
    if not web_ad:
        print("No kind: web_ad stores in config.")
    for sc in web_ad:
        base = sc.get("weekly_ad_url", "")
        seed = int(sc.get("ad_seed_id", 0))
        start = max(seed, _load_last_id(sc.get("name", "")))
        ad = _resolve_current_ad(base, start, int(sc.get("scan_window", 8)), date.today())
        print(f"\n{sc.get('name')}")
        print(f"  Base: {base}  (scan from {start})")
        if ad:
            print(f"  Ad:   id={ad['id']}  {ad['from']} → {ad['through']}  "
                  f"({len(ad['images'])} page image(s))")
            for u in ad["images"]:
                print(f"        {u}")
        else:
            print("  Ad:   (none resolved)")
        if "--tiles" in sys.argv and ad:
            print(f"  Tiles: {len(fetch_web_ad_flyers(sc, cfg))}")
