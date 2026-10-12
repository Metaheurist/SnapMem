"""
Sorts media into a date-based library and keeps `library.json` in sync.

Capture date, in order of preference:
1. the `memories_history.json` entry whose `mid`/`sid` matches the UUID in the file name
2. a `YYYY-MM-DD[_HH-MM-SS]` prefix in the file name (Snapchat export naming)
3. EXIF DateTimeOriginal (JPEG/TIFF, needs Pillow)
4. the file's modified time
"""

import filecmp
import json
import os
import queue
import re
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .events import EventThrottle, post_event
from .media import MEDIA_VIDEO_EXTS, is_media_file, remove_empty_dirs, unique_path_in_dir
from .memories import MemoryEntry, find_uuid

INDEX_NAME = "library.json"
_NAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[_ T](\d{2})[-:.](\d{2})[-:.](\d{2}))?")


@dataclass
class MediaRecord:
    path: str
    date: str
    kind: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def datetime(self) -> datetime:
        return datetime.fromisoformat(self.date)


def kind_of(path: Path) -> str:
    stem = path.stem.lower()
    if stem.endswith("-overlay") or stem.endswith("_overlay"):
        return "overlay"
    return "video" if path.suffix.lower() in MEDIA_VIDEO_EXTS else "photo"


def date_from_name(name: str) -> datetime | None:
    m = _NAME_DATE_RE.match(name)
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0), tzinfo=timezone.utc)
    except ValueError:
        return None


def date_from_exif(path: Path) -> datetime | None:
    if path.suffix.lower() not in {".jpg", ".jpeg", ".tif", ".tiff"}:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def capture_info(path: Path, id_index: dict[str, MemoryEntry] | None = None) -> tuple[datetime, MemoryEntry | None]:
    if id_index:
        uid = find_uuid(path.name)
        if uid and uid in id_index:
            return id_index[uid].date, id_index[uid]
    dt = date_from_name(path.name) or date_from_exif(path)
    if dt is None:
        dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return dt, None


def _same_content(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and filecmp.cmp(a, b, shallow=False)


def _norm(path: Path) -> str:
    # No filesystem access, unlike Path.resolve(), which dominated organize time on Windows.
    return os.path.normcase(os.path.abspath(path))


def _is_numbered_variant(src: Path, natural: Path) -> bool:
    """`<natural stem>_N<suffix>` in the same folder: already placed after a name clash."""
    if _norm(src.parent) != _norm(natural.parent) or src.suffix.lower() != natural.suffix.lower():
        return False
    return re.fullmatch(re.escape(natural.stem) + r"_\d+", src.stem) is not None


def target_dir(media_root: Path, layout: str, dt: datetime) -> Path:
    if layout == "year":
        return media_root / f"{dt:%Y}"
    if layout == "flat":
        return media_root
    return media_root / f"{dt:%Y}" / f"{dt:%m}"


def target_name(dt: datetime, kind: str, suffix: str) -> str:
    return f"{dt:%Y-%m-%d_%H-%M-%S}_{kind}{suffix.lower()}"


class Organizer:
    def __init__(
        self,
        media_root: Path,
        layout: str = "year_month",
        mode: str = "move",
        id_index: dict[str, MemoryEntry] | None = None,
        q: queue.Queue | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.media_root = media_root
        self.layout = layout
        self.mode = mode
        self.id_index = id_index or {}
        self.q = q
        self.stop_event = stop_event or threading.Event()
        self.records: dict[str, MediaRecord] = {}
        self.placed = 0
        self.skipped = 0
        self._throttle = EventThrottle(0.25)

    def place(self, src: Path, dt: datetime | None = None, entry: MemoryEntry | None = None) -> Path | None:
        if dt is None:
            dt, entry = capture_info(src, self.id_index)
        kind = kind_of(src)
        if entry is not None and kind != "overlay":
            kind = entry.kind
        dest_dir = target_dir(self.media_root, self.layout, dt)
        dest_dir.mkdir(parents=True, exist_ok=True)
        natural = dest_dir / target_name(dt, kind, src.suffix)

        if _norm(src) == _norm(natural) or _is_numbered_variant(src, natural):
            dest = src
        elif natural.exists() and _same_content(natural, src):
            self.skipped += 1
            dest = natural
            if self.mode == "move":
                src.unlink(missing_ok=True)
        else:
            dest = unique_path_in_dir(dest_dir, natural.name)
            if self.mode == "copy":
                shutil.copy2(src, dest)
            else:
                shutil.move(str(src), str(dest))
            self.placed += 1

        ts = dt.timestamp()
        try:
            os.utime(dest, (ts, ts))
        except OSError:
            pass
        rel = dest.relative_to(self.media_root).as_posix()
        self.records[rel] = MediaRecord(
            path=rel,
            date=dt.isoformat(),
            kind=kind,
            latitude=entry.latitude if entry else None,
            longitude=entry.longitude if entry else None,
        )
        return dest

    def organize_tree(self, root: Path, item_id: str | None = None) -> int:
        files = [p for p in root.rglob("*") if p.is_file() and is_media_file(p)]
        total = len(files) or 1
        for i, f in enumerate(files, start=1):
            if self.stop_event.is_set():
                raise RuntimeError("Cancelled")
            self.place(f)
            if self.q is not None and item_id and self._throttle.ready(item_id):
                post_event(self.q, "item_progress", id=item_id, percent=int(i * 100 / total))
        return len(files)

    def write_index(self) -> Path:
        existing = {r.path: r for r in read_index(self.media_root)}
        existing.update(self.records)
        return write_index(self.media_root, existing.values())


def read_index(media_root: Path) -> list[MediaRecord]:
    try:
        raw = json.loads((media_root / INDEX_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[MediaRecord] = []
    for item in raw.get("items", []) if isinstance(raw, dict) else []:
        try:
            out.append(MediaRecord(**item))
        except TypeError:
            continue
    return out


def write_index(media_root: Path, records) -> Path:
    media_root.mkdir(parents=True, exist_ok=True)
    items = sorted((asdict(r) for r in records), key=lambda r: (r["date"], r["path"]))
    path = media_root / INDEX_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "items": items}, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def load_library(media_root: Path) -> list[MediaRecord]:
    """Index entries whose files still exist, plus any media files the index does not know about."""
    if not media_root.is_dir():
        return []
    known = {r.path: r for r in read_index(media_root) if (media_root / r.path).is_file()}
    for f in media_root.rglob("*"):
        if not f.is_file() or not is_media_file(f):
            continue
        rel = f.relative_to(media_root).as_posix()
        if rel not in known:
            dt, _ = capture_info(f)
            known[rel] = MediaRecord(path=rel, date=dt.isoformat(), kind=kind_of(f))
    return sorted(known.values(), key=lambda r: r.date, reverse=True)


def reorganize_library(
    media_root: Path,
    layout: str,
    q: queue.Queue | None = None,
    stop_event: threading.Event | None = None,
) -> int:
    """Move existing library files into `layout`, keeping dates and locations from the index."""
    records = load_library(media_root)
    org = Organizer(media_root, layout=layout, mode="move", q=q, stop_event=stop_event)
    for r in records:
        if org.stop_event.is_set():
            raise RuntimeError("Cancelled")
        src = media_root / r.path
        entry = None
        if r.latitude is not None:
            entry = MemoryEntry(date=r.datetime, media_type="Video" if r.kind == "video" else "Image", download_link="", latitude=r.latitude, longitude=r.longitude)
        org.place(src, dt=r.datetime, entry=entry)
    remove_empty_dirs(media_root)
    write_index(media_root, org.records.values())
    return org.placed


def rebuild_index(media_root: Path) -> Path:
    return write_index(media_root, load_library(media_root))
