"""Turn fetched attachments (PDFs/images) into model-ready FlyerImage pages.

PDFs are rasterized one image per page (capped); images are downscaled so we
don't blow token budget. The store hint is derived from the saved filename
prefix (sender), to be refined by the model from the flyer content itself.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from providers.base import FlyerImage


def to_flyer_images(paths: list[Path], cfg: dict) -> list[FlyerImage]:
    ai = cfg.get("ai", {})
    max_pages = ai.get("max_pages_per_flyer", 8)
    max_px = ai.get("image_max_px", 1600)

    flyers: list[FlyerImage] = []
    for p in paths:
        hint = p.name.split("__", 1)[0]
        if p.suffix.lower() == ".pdf":
            flyers += _pdf_pages(p, hint, max_pages, max_px)
        else:
            flyers.append(_image_file(p, hint, max_px))
    return flyers


def _image_file(path: Path, hint: str, max_px: int) -> FlyerImage:
    img = Image.open(path).convert("RGB")
    return _encode(img, hint, max_px)


def _pdf_pages(path: Path, hint: str, max_pages: int, max_px: int) -> list[FlyerImage]:
    from pdf2image import convert_from_path  # needs poppler installed on host

    pages = convert_from_path(str(path), dpi=150)[:max_pages]
    return [_encode(pg.convert("RGB"), hint, max_px) for pg in pages]


def _encode(img: Image.Image, hint: str, max_px: int) -> FlyerImage:
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return FlyerImage(store_hint=hint, media_type="image/jpeg", data_b64=b64)
