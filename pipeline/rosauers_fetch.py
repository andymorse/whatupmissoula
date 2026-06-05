"""Fetch Rosauers' Missoula weekly ad — a web PDF, not an emailed flyer.

Rosauers' weekly email has a "Weekly Ad" button, but it only links to the
weekly-ad page (no PDF attached). Rather than depend on the email, we scrape
that page directly every run — the Missoula ad lives there as a PDF behind a
WordPress "pdf-poster-pro" PDF.js viewer:

    <iframe src=".../pdfjs-new/web/viewer.html?file=<PDF_URL>&#038;...">

So we scrape that page, pull the PDF URL out of the viewer's `file=` query param
(robust to the rotating /Week-N/ path and the ?v= cache-buster), download it, and
hand the pages to the same PDF→FlyerImage→vision path the emailed flyers use.

The flyer's printed "Ad Effective <from> thru <through>" line is read by the
vision step into the StoreWeek's valid_from / valid_through, so every Rosauers
deal — and any top-steal we surface from it — carries its expiry date.
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

DEFAULT_AD_URL = "https://www.rosauers.com/weekly-ad-missoula"


def fetch_rosauers_flyers(store_cfg: dict, cfg: dict) -> list[FlyerImage]:
    """Scrape the weekly-ad page, download the PDF, return vision-ready tiles."""
    page_url = store_cfg.get("weekly_ad_url", DEFAULT_AD_URL)
    name = store_cfg.get("name", "Rosauers")
    pdf_url = _extract_pdf_url(_get(page_url), page_url)
    if not pdf_url:
        raise RuntimeError(f"Rosauers: no weekly-ad PDF found on {page_url}")
    with tempfile.TemporaryDirectory() as td:
        pdf_path = Path(td) / "rosauers_weekly_ad.pdf"
        pdf_path.write_bytes(_get_bytes(pdf_url))
        # Reuse the shared PDF→image tiling (honours ai.max_pages_per_flyer etc.).
        return to_flyer_images_pairs([(pdf_path, name)], cfg)


def _extract_pdf_url(html: str, page_url: str) -> str | None:
    """Pull the PDF out of the pdf-poster-pro viewer iframe's `file=` param."""
    m = re.search(
        r'<iframe[^>]+src="([^"]*pdf-poster-pro[^"]*viewer\.html\?[^"]*)"',
        html, re.I,
    )
    if m:
        src = htmllib.unescape(m.group(1))        # &#038; → & so query parses
        file_vals = parse_qs(urlparse(src).query).get("file")
        if file_vals:
            return urljoin(page_url, unquote(file_vals[0]))
    # Fallback: a direct .pdf link somewhere on the page (if they drop the viewer).
    m2 = re.search(r'(https?://[^"\'<>]+?\.pdf)', html, re.I)
    return urljoin(page_url, htmllib.unescape(m2.group(1))) if m2 else None


def _get(url: str) -> str:
    return _get_bytes(url).decode("utf-8", "ignore")


def _get_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


if __name__ == "__main__":
    # Smoke test: resolve the PDF URL (no API needed). Pass --tiles to also
    # rasterize (needs poppler), printing the tile count.
    import sys

    from settings import load_config

    cfg = load_config()
    sc = next((s for s in cfg.get("stores", []) if s.get("kind") == "web_pdf"),
              {"name": "Rosauers"})
    page = sc.get("weekly_ad_url", DEFAULT_AD_URL)
    print(f"Page: {page}")
    print(f"PDF:  {_extract_pdf_url(_get(page), page)}")
    if "--tiles" in sys.argv:
        print(f"Tiles: {len(fetch_rosauers_flyers(sc, cfg))}")
