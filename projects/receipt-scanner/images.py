"""Preparing receipt photographs.

Two different jobs, deliberately kept apart:

* **for the archive** — the copy that replaces the paper receipt. Bigger, better
  quality, because once the original is in the bin this is the only evidence
  that the purchase happened.
* **for the model** — a smaller copy sent for extraction. The API downscales
  anything over 1568px on its long edge anyway, so sending more is paying to
  transmit pixels that get thrown away.

A phone photograph arrives rotated: the sensor writes landscape pixels and an
EXIF orientation tag saying which way is up. Anything that ignores that tag gets
a sideways receipt, and a sideways receipt extracts badly.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

#: The long edge above which the Anthropic API downscales images itself.
API_MAX_EDGE = 1568

#: The archive copy. Large enough to read line items back off later.
ARCHIVE_MAX_EDGE = 2200

THUMBNAIL_MAX_EDGE = 480

API_MEDIA_TYPE = "image/jpeg"

#: What a phone or a scanner might hand us.
ACCEPTED_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff",
}

_HEIF_READY = False


def _enable_heif() -> bool:
    """Register HEIC/HEIF support if pillow-heif is installed.

    Pixel phones write JPEG through the browser's camera capture, but a photo
    picked out of the gallery can be HEIC. Without this the upload fails with an
    unhelpful "cannot identify image file".
    """
    global _HEIF_READY
    if _HEIF_READY:
        return True
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
        _HEIF_READY = True
    except ImportError:
        pass
    return _HEIF_READY


def open_normalized(source: str | Path | bytes) -> Image.Image:
    """Open an image, apply its EXIF rotation, and drop to RGB.

    Raises ValueError with a message worth showing a user — not a Pillow
    traceback — because this is the first place a bad upload fails.
    """
    _enable_heif()
    try:
        if isinstance(source, bytes):
            img = Image.open(io.BytesIO(source))
        else:
            img = Image.open(source)
        img.load()
    except FileNotFoundError:
        raise ValueError(f"no such file: {source}") from None
    except Exception as exc:
        suffix = Path(str(source)).suffix.lower() if not isinstance(source, bytes) else ""
        if suffix in {".heic", ".heif"} and not _HEIF_READY:
            raise ValueError(
                "this is an HEIC photo and pillow-heif is not installed — "
                "run: pip install pillow-heif"
            ) from exc
        raise ValueError(f"could not read this as an image ({exc})") from exc

    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    return img


def _fit(img: Image.Image, max_edge: int) -> Image.Image:
    if max(img.size) <= max_edge:
        return img
    scale = max_edge / max(img.size)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.LANCZOS)


def _encode(img: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def for_model(img: Image.Image) -> tuple[bytes, str]:
    """The copy sent for extraction. Returns (jpeg_bytes, media_type)."""
    return _encode(_fit(img, API_MAX_EDGE), quality=85), API_MEDIA_TYPE


def for_archive(img: Image.Image) -> bytes:
    """The copy that replaces the paper."""
    return _encode(_fit(img, ARCHIVE_MAX_EDGE), quality=88)


def for_thumbnail(img: Image.Image) -> bytes:
    """The copy the library grid shows."""
    return _encode(_fit(img, THUMBNAIL_MAX_EDGE), quality=80)


def describe(img: Image.Image) -> str:
    return f"{img.width}x{img.height}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python images.py <image>")
        raise SystemExit(2)

    image = open_normalized(sys.argv[1])
    model_bytes, media_type = for_model(image)
    archive_bytes = for_archive(image)
    thumb_bytes = for_thumbnail(image)
    print(f"source    {describe(image)}")
    print(f"model     {len(model_bytes) / 1024:.0f} KB  {media_type}")
    print(f"archive   {len(archive_bytes) / 1024:.0f} KB")
    print(f"thumbnail {len(thumb_bytes) / 1024:.0f} KB")
