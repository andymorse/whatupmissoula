"""Fetch CHEF'STORE Missoula biweekly specials as structured Deal objects.

CHEF'STORE (US Foods' restaurant-supply chain) doesn't email a flyer — the
weekly email links to chefstore.com/specials/ where you pick a location and
then a specials tab. The biweekly specials page embeds every product as
structured JSON (`productData`), so we can skip vision extraction entirely
and parse deals directly. Cheaper, faster, exact prices.

Flow:
  1. GET /content/setStore/<store_id>/specials/ — sets the per-store cookie
     and 302s to that store's hotsheet landing (/content/hotsheet/<NN>/).
  2. From the landing, scrape the "Biweekly Specials" tab URL
     (/content/hotsheet/<NN>/<section_id>/).
  3. GET that URL + "/list/" — list view embeds all products as
     `productData : { COLUMNS:[...], DATA:[[...],...] }`.
  4. Parse rows → Deal objects.

Output is a StoreWeek with kind="bulk_wholesale" — CHEF'STORE prices are
per-case at restaurant scale, and the badge tells viewers what they're
looking at.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Optional

from schema import Deal, StoreWeek

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Missoula CHEF'STORE is store #505 (2501 Brooks St). Confirmed from the
# location picker at /specials/ (505-Missoula.webp tile).
MISSOULA_STORE_ID = 505

# The "Biweekly Specials" tab is the headline ad — what the email points at.
# (Other tabs: "This Week Specials", "Cambro Specials" — distinct collections.)
BIWEEKLY_ANCHOR = "biweekly specials"


def fetch_chefstore_deals(store_id: int = MISSOULA_STORE_ID,
                          tab: str = BIWEEKLY_ANCHOR,
                          base: str = "https://www.chefstore.com") -> StoreWeek:
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", UA), ("Accept-Language", "en-US,en;q=0.9")]

    # Step 1 — set the location cookie, follow into the store's hotsheet.
    landing_url = f"{base}/content/setStore/{store_id}/specials/"
    landing = _get(opener, landing_url)
    # Step 2 — find the biweekly tab URL on that landing page.
    tab_url = _find_tab(landing, base, tab)
    if not tab_url:
        raise RuntimeError(f"CHEF'STORE: couldn't find {tab!r} tab from {landing_url}")
    # Step 3 — list view embeds the product JSON.
    list_url = tab_url.rstrip("/") + "/list/"
    page = _get(opener, list_url)
    # Step 4 — parse.
    deals = _parse_products(page)
    return StoreWeek(
        name="CHEF'STORE (Missoula)",
        kind="bulk_wholesale",
        valid_from=None,
        valid_through=_max_end_date(page),
        deals=deals,
    )


def _get(opener, url: str) -> str:
    with opener.open(url, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _find_tab(html: str, base: str, anchor_text: str) -> Optional[str]:
    """Pick the <a href="/content/hotsheet/NN/MMMM/"> whose text matches anchor_text."""
    needle = anchor_text.lower()
    for m in re.finditer(r'<a\s+href="(/content/hotsheet/\d+/\d+/?)"\s*>(.*?)</a>',
                         html, re.I | re.S):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip().lower()
        if needle in text:
            return urllib.parse.urljoin(base, m.group(1))
    return None


def _parse_products(html: str) -> list[Deal]:
    """Pull `productData : { COLUMNS:[...], DATA:[[...],...] }` out of the page."""
    m = re.search(
        r'productData\s*:\s*\{\s*"COLUMNS"\s*:\s*(\[[^\]]+\])\s*,\s*"DATA"\s*:\s*(\[\[.*?\]\])\s*\}',
        html, re.S,
    )
    if not m:
        return []
    cols = json.loads(m.group(1))
    rows = json.loads(m.group(2))
    idx = {c: i for i, c in enumerate(cols)}

    def get(row, key):
        i = idx.get(key)
        return row[i] if i is not None and i < len(row) else None

    deals: list[Deal] = []
    for row in rows:
        desc = get(row, "ITEMDESC")
        if not desc:
            continue
        reg = _num(get(row, "UNITREGPRICE"))
        sale = _num(get(row, "UNITSELLPRICE"))
        size = get(row, "ITEMSIZE")
        caveats: list[str] = []
        if size:
            caveats.append(f"case pack: {size}")
        deals.append(Deal(
            item=_title(desc),
            category=_category(get(row, "CATEGORY"), get(row, "AREA")),
            sale_price=sale,
            regular_price=reg,
            unit=_unit_label(size),
            unit_price=None,
            requires_loyalty=False,
            caveats=caveats,
            confidence="high",
        ))
    return deals


# Keyword → schema category, in priority order. CATEGORY values look like
# "BEEF, TENDERLOIN, RAW, REFRIGERATED" or "HOT DOGS, BEEF, FROZEN" — first
# match wins, so meat keywords beat the "FROZEN" suffix (a frozen hot dog is
# still meat to a shopper). ICE CREAM gets pinned to frozen ahead of "CREAM".
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("ICE CREAM", "frozen"),
    ("BEEF", "meat_seafood"), ("PORK", "meat_seafood"),
    ("CHICKEN", "meat_seafood"), ("TURKEY", "meat_seafood"),
    ("LAMB", "meat_seafood"), ("HOT DOG", "meat_seafood"),
    ("SAUSAGE", "meat_seafood"), ("BACON", "meat_seafood"),
    ("FISH", "meat_seafood"), ("SHRIMP", "meat_seafood"),
    ("SEAFOOD", "meat_seafood"), ("CRAB", "meat_seafood"),
    ("MILK", "dairy_eggs"), ("CHEESE", "dairy_eggs"),
    ("YOGURT", "dairy_eggs"), ("BUTTER", "dairy_eggs"),
    ("SOUR CREAM", "dairy_eggs"), ("EGG", "dairy_eggs"),
    ("DAIRY", "dairy_eggs"), ("DRESSING", "dairy_eggs"),
    ("BREAD", "bakery"), ("BAGEL", "bakery"),
    ("TORTILLA", "bakery"), ("BAKERY", "bakery"),
    ("WATERMELON", "produce"), ("BANANA", "produce"),
    ("APPLE", "produce"), ("LETTUCE", "produce"),
    ("ONION", "produce"), ("TOMATO", "produce"),
    ("PRODUCE", "produce"), ("FRUIT", "produce"),
    ("SODA", "beverages"), ("DRINKS", "beverages"),
    ("JUICE", "beverages"), ("WATER", "beverages"),
    ("COFFEE", "beverages"), ("TEA", "beverages"),
    ("BEVERAGE", "beverages"),
    ("SNACK", "snacks"), ("CHIP", "snacks"),
    ("CRACKER", "snacks"), ("POPCORN", "snacks"),
    ("CANDY", "snacks"), ("CHOCOLATE", "snacks"),
    ("FROZEN", "frozen"),  # catch-all after specific overrides above
    ("SUGAR", "pantry"), ("OIL", "pantry"),
    ("SAUCE", "pantry"), ("JELL", "pantry"),
    ("JAM", "pantry"), ("SYRUP", "pantry"),
    ("DESSERT TOPPING", "pantry"),
]

_AREA_FALLBACK = {
    "produce": "produce", "freezer": "frozen", "grocery": "pantry",
    "deli/dairy": "dairy_eggs", "deli": "dairy_eggs", "dairy": "dairy_eggs",
}


def _category(category: Optional[str], area: Optional[str]) -> str:
    if category:
        c = category.upper()
        for kw, cat in _CATEGORY_KEYWORDS:
            if kw in c:
                return cat
    if area:
        a = area.lower()
        for kw, cat in _AREA_FALLBACK.items():
            if kw in a:
                return cat
    return "other"


def _unit_label(size: Optional[str]) -> Optional[str]:
    # CHEF'STORE sizes look like "12/6.67 LBA" or "6/64 OZ" — we only surface a
    # generic unit when one is obvious. unit_price stays None: per-case pricing
    # is not a household-comparable $/lb without further math.
    if not size:
        return None
    s = size.lower()
    if "lb" in s:
        return "$/case (lb pack)"
    if "oz" in s:
        return "$/case (oz pack)"
    return "$/case"


def _title(s: str) -> str:
    """Convert SHOUTY-CASE item names to title case, preserving short acronyms."""
    return " ".join(
        w if (w.isupper() and len(w) <= 3) else w.capitalize()
        for w in s.lower().split()
    )


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _max_end_date(html: str) -> Optional[str]:
    # Find the latest UNITENDDATE on the page so the StoreWeek carries a
    # reasonable "valid through". Dates look like "2026-05-31 00:00:00.0000000".
    dates = re.findall(r'"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}', html)
    return max(dates) if dates else None


if __name__ == "__main__":
    # Smoke test: print the first 10 deals.
    sw = fetch_chefstore_deals()
    print(f"Store: {sw.name}  kind={sw.kind}  through={sw.valid_through}")
    print(f"Deals: {len(sw.deals)}")
    for d in sw.deals[:10]:
        po = f" ({d.percent_off}% off)" if d.percent_off else ""
        print(f"  • [{d.category}] {d.item} — ${d.sale_price} (reg ${d.regular_price}){po}")
        for c in d.caveats:
            print(f"      · {c}")
