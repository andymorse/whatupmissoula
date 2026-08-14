"""Fetch a store's weekly ad when it's a web-hosted image flyer on a ShopHero site.

Some stores publish their weekly ad as a full-page JPG on a ShopHero-powered
storefront (Nuxt/Vue), not as an emailed flyer or a PDF. Orange Street Food Farm
is the first: the ad lives at `…/weekly-ads`, and the page carries both the page
image URL and the printed date range.

  • The page used to be *server*-rendered, so a plain GET was enough. As of
    Aug 2026 ShopHero renders the ad **client-side** — every ad URL now returns
    the same ~42KB Nuxt shell with an empty `__NUXT_DATA__` payload, so urllib
    sees no date range and no images at all. We render with headless Chromium
    (already a dependency for web_flyer.py) and parse the resulting DOM. The
    regexes below are unchanged; only the fetch moved.

  • The base `/weekly-ads` URL renders the *current* ad on its own, so there is
    nothing to scan. This replaced an id-scanning approach (`ad_seed_id` +
    `scan_window` + cached last-id state) that existed only because the old
    server-rendered pages had to be probed one id at a time — ids were not a
    stable +1 each week. A stale seed was a recurring source of breakage; the
    base URL can't go stale.

  • A multi-page ad renders every page's <img>, so one render gets the whole ad;
    we pull all `ad_<id>_page_<n>_<hash>.jpg` URLs and feed them to the shared
    image→vision path. The source JPGs are downloaded directly — sharper input
    for vision than screenshotting the rendered page.

Config (a store with `kind: web_ad`):

    - name: "Orange Street Food Farm"
      kind: "web_ad"
      weekly_ad_url: "https://www.orangestreetfoodfarm.com/weekly-ads"
      render_wait_ms: 20000   # optional; Chromium virtual-time budget
"""
from __future__ import annotations

import html as htmllib
import re
import subprocess
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# "Aug 12, 2026 - Aug 18, 2026" — the ad's printed valid range.
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
    """Render the current web ad, download its page image(s), return vision tiles."""
    name = store_cfg.get("name", "Store")
    base_url = store_cfg.get("weekly_ad_url")
    if not base_url:
        raise RuntimeError(f"{name}: kind: web_ad needs a weekly_ad_url in config")
    wait_ms = int(store_cfg.get("render_wait_ms", 20000))

    ad = _read_ad(_render_dom(base_url, wait_ms))
    if not ad:
        raise RuntimeError(
            f"{name}: rendered {base_url} but found no ad date range or page images. "
            "The page may have changed again, or Chromium was blocked."
        )
    if not (ad["from"] <= date.today() <= ad["through"]):
        # Not fatal — the store sometimes posts the next week's ad early, and
        # showing the ad they're actually publishing beats showing nothing.
        print(f"  ! {name}: ad range {ad['from']}..{ad['through']} doesn't cover today "
              f"({date.today()}) — using it anyway")

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


def _read_ad(html: str) -> dict | None:
    """Parse a rendered ad page into its date range + image urls, or None."""
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
    return {"from": valid_from, "through": valid_through, "images": imgs}


def _render_dom(url: str, wait_ms: int, chromium: str = "chromium") -> str:
    """Load the page in headless Chromium and return the post-JS DOM."""
    safe_url(url)  # block file:// / internal-host links before chromium loads them
    cmd = [
        chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
        f"--user-agent={UA}", "--accept-lang=en-US,en;q=0.9",
        f"--virtual-time-budget={wait_ms}", "--dump-dom", url,
    ]
    out = subprocess.run(cmd, check=True, capture_output=True,
                         timeout=wait_ms / 1000 + 30)
    dom = out.stdout.decode("utf-8", "replace")
    # An error/blocked page renders as a near-empty shell; the real ad page is
    # ~75KB. Fail loudly rather than reporting "no ad found".
    if len(dom) < 5000:
        raise RuntimeError(f"Rendered DOM suspiciously small ({len(dom)}B) for {url} "
                           "— likely blocked or an error page.")
    return dom


def _ad_image_urls(html: str) -> list[str]:
    """All distinct ad page image URLs, ordered by page number."""
    seen: dict[str, int] = {}
    for m in _AD_IMG_RE.finditer(html):
        seen.setdefault(m.group(0), int(m.group(1)))
    return sorted(seen, key=seen.get)


def _get_image_bytes(url: str) -> bytes:
    """Download an ad image, following the host's occasional meta-refresh page."""
    data = _get_bytes(url)
    head = data[:200].lstrip().lower()
    if head.startswith((b"<!doctype", b"<html")):
        m = _META_REFRESH_RE.search(data.decode("utf-8", "ignore"))
        if m:
            data = _get_bytes(htmllib.unescape(m.group(1)))
    return data


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
        print(f"\n{sc.get('name')}")
        print(f"  Base: {base}")
        try:
            ad = _read_ad(_render_dom(base, int(sc.get("render_wait_ms", 20000))))
        except Exception as e:
            print(f"  Ad:   render failed — {type(e).__name__}: {e}")
            continue
        if ad:
            print(f"  Ad:   {ad['from']} → {ad['through']}  "
                  f"({len(ad['images'])} page image(s))")
            for u in ad["images"]:
                print(f"        {u}")
        else:
            print("  Ad:   (none parsed from rendered DOM)")
        if "--tiles" in sys.argv and ad:
            print(f"  Tiles: {len(fetch_web_ad_flyers(sc, cfg))}")
