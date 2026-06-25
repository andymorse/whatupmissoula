"""Render a web-hosted flyer (SPA, Flipp link, etc.) into FlyerImage tiles.

Many stores — including the "email" ones — don't attach a flyer; they link to a
JavaScript-rendered weekly-ad page. We load it in headless Chromium, screenshot
the fully-rendered page, and slice the tall image into vision-friendly tiles so
the model can read prices without the whole flyer being downscaled to mush.

Requires the `chromium` binary on PATH (apt install chromium).
"""
from __future__ import annotations

import base64
import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from providers.base import FlyerImage
from url_guard import safe_url

# A normal Chrome UA — the default headless UA is often blocked by bot filters.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def render_flyer(url: str, store_hint: str, *, width: int = 1400,
                 wait_ms: int = 25000, tile_height: int = 1500,
                 overlap: int = 140, chromium: str = "chromium") -> list[FlyerImage]:
    """Screenshot a rendered page and return it sliced into FlyerImage tiles."""
    png = _screenshot(url, width, wait_ms, chromium)
    return _slice(png, store_hint, tile_height, overlap)


def _screenshot(url: str, width: int, wait_ms: int, chromium: str) -> bytes:
    safe_url(url)  # block file:// / internal-host links before chromium loads them
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "shot.png"
        cmd = [
            chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--hide-scrollbars", f"--user-agent={_UA}",
            "--accept-lang=en-US,en;q=0.9",
            f"--window-size={width},2400",
            f"--virtual-time-budget={wait_ms}",
            f"--screenshot={out}", url,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=wait_ms / 1000 + 30)
        data = out.read_bytes()
    img = Image.open(io.BytesIO(data))
    if img.mode != "RGB":
        img = img.convert("RGB")
    # Guard against an error/blocked page rendering nearly blank.
    if img.height < 400:
        raise RuntimeError(f"Rendered page suspiciously short ({img.size}) — likely blocked.")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _slice(png: bytes, store_hint: str, tile_height: int, overlap: int) -> list[FlyerImage]:
    img = Image.open(io.BytesIO(png))
    w, h = img.size
    tiles: list[FlyerImage] = []
    y = 0
    while y < h:
        bottom = min(y + tile_height, h)
        tile = img.crop((0, y, w, bottom))
        buf = io.BytesIO()
        tile.save(buf, format="JPEG", quality=85)
        tiles.append(FlyerImage(
            store_hint=store_hint,
            media_type="image/jpeg",
            data_b64=base64.b64encode(buf.getvalue()).decode("ascii"),
        ))
        if bottom >= h:
            break
        y = bottom - overlap
    return tiles
