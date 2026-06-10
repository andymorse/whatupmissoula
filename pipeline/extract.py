"""Turn flyer files (PDFs/images) into model-ready FlyerImage pages.

Used by two input paths:
- email attachments (store hint comes from the saved filename's sender prefix)
- the manual `--images <dir>` drop (store hint comes from --store or a subfolder)

PDF pages are rasterized; images are downscaled to stay within token budget, and
very tall images (e.g. a full stitched flyer screenshot) are sliced into tiles so
prices stay legible instead of being shrunk to mush.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from providers.base import FlyerImage

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
FLYER_EXTS = IMG_EXTS | {".pdf"}


def gather_flyer_files(root: str | Path, default_store: str | None = None) -> list[tuple[Path, str]]:
    """Collect (path, store_hint) pairs from a file or directory.

    A flat file uses default_store (or its filename stem). For a directory, files
    inside a subfolder take that subfolder's name as the store hint — so you can
    organize drops like  images/Rosauers/ad.jpg, images/Albertsons/page1.png.
    """
    root = Path(root)
    if root.is_file():
        return [(root, default_store or root.stem)]
    pairs: list[tuple[Path, str]] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in FLYER_EXTS:
            hint = p.parent.name if p.parent != root else (default_store or p.stem)
            pairs.append((p, hint))
    return pairs


def archive_drops(files: list[Path], archive_root: Path, week_of: str) -> None:
    """Move processed drop files into archive_root/<week_of>/<store>/ so the next
    run doesn't re-analyze them. Best-effort: keeps the store-subfolder name.
    """
    import shutil

    for f in files:
        if not f.exists():
            continue
        dest = archive_root / week_of / f.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest / f.name))


def to_flyer_images(paths: list[Path], cfg: dict) -> list[FlyerImage]:
    """Email/attachment path: hint from the saved filename's 'sender__' prefix."""
    pairs = [(p, p.name.split("__", 1)[0]) for p in paths]
    return to_flyer_images_pairs(pairs, cfg)


def to_flyer_images_pairs(pairs: list[tuple[Path, str]], cfg: dict) -> list[FlyerImage]:
    ai = cfg.get("ai", {})
    max_pages = ai.get("max_pages_per_flyer", 8)
    max_px = ai.get("image_max_px", 1600)

    flyers: list[FlyerImage] = []
    for path, hint in pairs:
        if path.suffix.lower() == ".pdf":
            flyers += _pdf_pages(path, hint, max_pages, max_px)
        else:
            flyers += _image_to_flyers(Image.open(path).convert("RGB"), hint, max_px)
    return flyers


def _pdf_pages(path: Path, hint: str, max_pages: int, max_px: int) -> list[FlyerImage]:
    from pdf2image import convert_from_path  # needs poppler installed on host

    out: list[FlyerImage] = []
    for pg in convert_from_path(str(path), dpi=150)[:max_pages]:
        out += _image_to_flyers(pg.convert("RGB"), hint, max_px)
    return out


def _image_to_flyers(img: Image.Image, hint: str, max_px: int,
                     tile_h: int = 1600, overlap: int = 140) -> list[FlyerImage]:
    """Single tile for normal images; slice vertically for very tall ones."""
    w, h = img.size
    if h <= tile_h * 1.3:
        return [_encode(img, hint, max_px)]
    # Tall image: downscale width if needed, then slice into overlapping tiles.
    if w > max_px:
        img = img.resize((max_px, int(h * max_px / w)))
        w, h = img.size
    tiles: list[FlyerImage] = []
    y = 0
    while y < h:
        bottom = min(y + tile_h, h)
        tiles.append(_encode(img.crop((0, y, w, bottom)), hint, max_px))
        if bottom >= h:
            break
        y = bottom - overlap
    return tiles


def _encode(img: Image.Image, hint: str, max_px: int) -> FlyerImage:
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return FlyerImage(store_hint=hint, media_type="image/jpeg", data_b64=b64)
