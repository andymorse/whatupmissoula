"""Fetch a store's weekly ad when it's a web-hosted PDF, not an emailed flyer.

Some stores don't attach (or usefully email) their ad — the deals live in a PDF
on a public weekly-ad page. Examples:

  • Rosauers — the Missoula ad sits behind a WordPress "pdf-poster-pro" PDF.js
    viewer: <iframe src=".../viewer.html?file=<PDF_URL>&#038;...">.
  • Good Food Store — the sale-flyer page links a full-flyer PDF directly. Its
    on-page JPG page previews are lazy-loaded, so a headless screenshot only
    captures page 1; the PDF is the reliable, complete source.

For a store with `kind: web_pdf` we scrape its `weekly_ad_url`, pull out the PDF
(from the viewer's `file=` param, else a direct .pdf link — preferring a
flyer-ish one), download it, and hand the pages to the same
PDF→FlyerImage→vision path the emailed flyers use. Runs every cycle, independent
of email. The flyer's printed "Effective <from> thru <through>" line is read by
the vision step into valid_from / valid_through, so the deals carry expiry dates.
"""
from __future__ import annotations

import html as htmllib
import re
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from extract import to_flyer_images_pairs
from providers.base import FlyerImage
from url_guard import safe_url

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def fetch_web_pdf_flyers(store_cfg: dict, cfg: dict) -> list[FlyerImage]:
    """Scrape a store's weekly-ad page, download its PDF, return vision tiles."""
    name = store_cfg.get("name", "Store")
    page_url = store_cfg.get("weekly_ad_url")
    if not page_url:
        raise RuntimeError(f"{name}: kind: web_pdf needs a weekly_ad_url in config")
    pdf_url = _extract_pdf_url(_get(page_url), page_url)
    if not pdf_url:
        raise RuntimeError(f"{name}: no weekly-ad PDF found on {page_url}")
    with tempfile.TemporaryDirectory() as td:
        pdf_path = Path(td) / "weekly_ad.pdf"
        pdf_path.write_bytes(_get_bytes(pdf_url))
        # Reuse the shared PDF→image tiling (honours ai.max_pages_per_flyer etc.).
        return to_flyer_images_pairs([(pdf_path, name)], cfg)


def _extract_pdf_url(html: str, page_url: str) -> str | None:
    """Find the ad PDF on a weekly-ad page.

    First the pdf-poster-pro PDF.js viewer iframe's `file=` param (Rosauers);
    otherwise a direct .pdf link on the page (Good Food Store), preferring one
    whose URL looks flyer-ish so we don't grab some unrelated PDF.
    """
    m = re.search(
        r'<iframe[^>]+src="([^"]*pdf-poster-pro[^"]*viewer\.html\?[^"]*)"',
        html, re.I,
    )
    if m:
        src = htmllib.unescape(m.group(1))        # &#038; → & so query parses
        file_vals = parse_qs(urlparse(src).query).get("file")
        if file_vals:
            return urljoin(page_url, unquote(file_vals[0]))
    # Fallback: a direct .pdf link. Prefer flyer-ish URLs over any stray PDF.
    pdfs = re.findall(r'https?://[^"\'<>\s]+?\.pdf', html, re.I)
    if pdfs:
        flyerish = [p for p in pdfs if re.search(r'flyer|sale|ad|week', p, re.I)]
        return urljoin(page_url, htmllib.unescape((flyerish or pdfs)[0]))
    return None


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
    # Smoke test: resolve the PDF URL for each web_pdf store (no API needed).
    # Pass --tiles to also rasterize (needs poppler), printing the tile count.
    import sys

    from settings import load_config

    cfg = load_config()
    web_pdf = [s for s in cfg.get("stores", []) if s.get("kind") == "web_pdf"]
    if not web_pdf:
        print("No kind: web_pdf stores in config.")
    for sc in web_pdf:
        page = sc.get("weekly_ad_url", "")
        print(f"\n{sc['name']}")
        print(f"  Page: {page}")
        print(f"  PDF:  {_extract_pdf_url(_get(page), page) if page else '(no weekly_ad_url)'}")
        if "--tiles" in sys.argv and page:
            print(f"  Tiles: {len(fetch_web_pdf_flyers(sc, cfg))}")
