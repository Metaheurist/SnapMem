"""
Builds a small fake Snapchat export (ZIP + memories_history.json) for the self-test,
the test suite and README screenshots. No real user data is involved.
"""

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PALETTE = [(255, 252, 0), (64, 196, 255), (255, 99, 132), (120, 220, 140), (180, 120, 255), (255, 170, 60)]


def _jpeg_bytes(color: tuple[int, int, int], size: int = 96) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        # Smallest valid JPEG-looking payload; the self-test only checks sorting.
        return b"\xff\xd8\xff\xe0" + bytes(color) * 32 + b"\xff\xd9"
    img = Image.new("RGB", (size, size), (24, 24, 28))
    draw = ImageDraw.Draw(img)
    draw.ellipse((size * 0.15, size * 0.15, size * 0.85, size * 0.85), fill=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _mp4_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64


def build_sample_export(out_dir: Path, count: int = 12, start: datetime | None = None, name: str = "mydata~sample.zip") -> Path:
    """Write a ZIP shaped like a Snapchat export and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    start = start or datetime(2023, 1, 14, 9, 30, 0, tzinfo=timezone.utc)
    zip_path = out_dir / name
    saved_media = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(count):
            dt = start + timedelta(days=i * 23, hours=i * 3, minutes=i * 7)
            mid = str(uuid.UUID(int=i + 1))
            is_video = i % 4 == 3
            ext = ".mp4" if is_video else ".jpg"
            body = _mp4_bytes() if is_video else _jpeg_bytes(_PALETTE[i % len(_PALETTE)])
            zf.writestr(f"memories/{dt:%Y-%m-%d}_{mid}-main{ext}", body)
            if i % 5 == 0:
                zf.writestr(f"memories/{dt:%Y-%m-%d}_{mid}-overlay.png", _jpeg_bytes((255, 255, 255), 48))
            saved_media.append(
                {
                    "Date": f"{dt:%Y-%m-%d %H:%M:%S} UTC",
                    "Media Type": "Video" if is_video else "Image",
                    "Location": f"Latitude, Longitude: {51.5 + i / 100:.4f}, {-0.12 - i / 100:.4f}",
                    "Download Link": f"https://app.snapchat.com/dmd/memories?uid=sample&sid={mid}&mid={mid}&ts=0&sig=sample",
                }
            )
        zf.writestr("json/memories_history.json", json.dumps({"Saved Media": saved_media}, indent=1))
        zf.writestr("../escape.txt", "zip-slip probe")
    return zip_path
