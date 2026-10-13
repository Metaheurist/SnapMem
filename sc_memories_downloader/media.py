import shutil
from pathlib import Path

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


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTS and not path.name.startswith("._")


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


def remove_empty_dirs(root: Path) -> None:
    dirs = sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        try:
            d.rmdir()
        except OSError:
            pass


def flatten_media_directory(media_dir: Path) -> tuple[int, str | None]:
    """Move every file from subfolders of media_dir into media_dir (flat). Removes empty dirs."""
    media_dir = media_dir.resolve()
    if not media_dir.is_dir():
        return 0, "Media folder does not exist."

    to_move = [p for p in media_dir.rglob("*") if p.is_file() and p.parent != media_dir]
    if not to_move:
        return 0, None

    moved = 0
    for src in sorted(to_move, key=lambda p: len(p.parts), reverse=True):
        dst = unique_path_in_dir(media_dir, src.name)
        shutil.move(str(src), str(dst))
        moved += 1

    remove_empty_dirs(media_dir)
    return moved, None
