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


def unique_path_in_dir(directory: Path, filename: str) -> Path:
    """Return directory / filename, or stem_2.ext, stem_3.ext, ... if that name is taken."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 2
    while True:
        cand = directory / f"{stem}_{n}{suffix}"
        if not cand.exists():
            return cand
        n += 1


def flatten_media_directory(media_dir: Path) -> tuple[int, str | None]:
    """Move every file from subfolders of media_dir into media_dir (flat). Removes empty dirs."""
    media_dir = media_dir.resolve()
    if not media_dir.is_dir():
        return 0, "Media folder does not exist."

    # Files not directly under media_dir (any depth).
    to_move = [p for p in media_dir.rglob("*") if p.is_file() and p.parent != media_dir]
    if not to_move:
        return 0, None

    moved = 0
    for src in sorted(to_move, key=lambda p: len(p.parts), reverse=True):
        dst = unique_path_in_dir(media_dir, src.name)
        shutil.move(str(src), str(dst))
        moved += 1

    # Remove empty directories under media_dir (deepest first).
    dirs = sorted(
        [p for p in media_dir.rglob("*") if p.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for d in dirs:
        if d == media_dir:
            continue
        try:
            d.rmdir()
        except OSError:
            pass

    return moved, None


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

        base = destination_dir / src.name
        # Copy (not move) so the extracted folder still exists.
        # If the natural filename already exists with identical size, skip to save time.
        if base.exists() and base.stat().st_size == src.stat().st_size:
            continue

        dst = unique_path_in_dir(destination_dir, src.name)
        shutil.copy2(src, dst)
        copied += 1

    post_event(q, "current_progress", percent=100)
    post_event(q, "log", message=f"Media copied ({copied} files) from {root_dir.name}")
    return copied

