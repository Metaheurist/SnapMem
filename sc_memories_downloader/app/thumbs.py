import io
from functools import lru_cache
from pathlib import Path

THUMB_SIZE = 256


@lru_cache(maxsize=1024)
def _thumbnail(path: str, mtime_ns: int) -> bytes | None:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im.draft("RGB", (THUMB_SIZE * 2, THUMB_SIZE * 2))
            im = ImageOps.exif_transpose(im)
            im.thumbnail((THUMB_SIZE, THUMB_SIZE))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=80)
            return buf.getvalue()
    except Exception:
        return None


def thumbnail(path: Path) -> bytes | None:
    """Small JPEG preview of a photo, cached per file version. None if it can't be read."""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    return _thumbnail(str(path), mtime)
