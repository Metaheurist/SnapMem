import queue
import shutil
import threading
from pathlib import Path

from .events import post_event

MEDIA_IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".svg",
}
MEDIA_VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".wmv",
    ".webm",
    ".mpeg",
    ".mpg",
    ".m4v",
    ".3gp",
    ".3gpp",
}
MEDIA_EXTS = MEDIA_IMAGE_EXTS | MEDIA_VIDEO_EXTS


def copy_media_from_tree(
    root_dir: Path,
    destination_dir: Path,
    stop_event: threading.Event,
    q: queue.Queue,
    phase_text: str,
) -> int:
    files = [p for p in root_dir.rglob("*") if p.is_file()]
    total = len(files)
    copied = 0

    destination_dir.mkdir(parents=True, exist_ok=True)
    for idx, src in enumerate(files, start=1):
        if stop_event.is_set():
            raise RuntimeError("Cancelled")

        suffix = src.suffix.lower()
        if suffix not in MEDIA_EXTS:
            continue

        percent = int(idx * 100 / total) if total else 100
        post_event(q, "set_phase", text=phase_text)
        post_event(q, "current_progress", percent=percent)

        rel = src.relative_to(root_dir)
        dst = destination_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Copy (not move) so the extracted folder still exists
        # If a file exists and is identical size, skip to save time.
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            continue

        shutil.copy2(src, dst)
        copied += 1

    post_event(q, "current_progress", percent=100)
    post_event(q, "log", message=f"Media copied ({copied} files) from {root_dir.name}")
    return copied

