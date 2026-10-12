import queue
import shutil
import threading
import zipfile
from pathlib import Path, PureWindowsPath

from .events import EventThrottle, post_event


def is_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def safe_extract_zip(
    zip_path: Path,
    extract_to: Path,
    stop_event: threading.Event,
    q: queue.Queue,
    item_id: str | None = None,
    throttle: EventThrottle | None = None,
) -> int:
    """
    Extract `zip_path` into `extract_to`, skipping any entry that would land outside it
    (absolute paths, `..`, drive letters). Returns the number of files written.
    """
    throttle = throttle or EventThrottle(0.25)
    extract_to.mkdir(parents=True, exist_ok=True)
    base = extract_to.resolve()
    written = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total = len(members) or 1
        for idx, m in enumerate(members, start=1):
            if stop_event.is_set():
                raise RuntimeError("Cancelled")

            name = m.filename.replace("\\", "/")
            target = (base / name).resolve()
            if not name or PureWindowsPath(name).drive or not is_within(base, target) or (target == base and not m.is_dir()):
                post_event(q, "log", message=f"Skipped unsafe path in {zip_path.name}: {m.filename}")
                continue

            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            written += 1

            if item_id and throttle.ready(item_id):
                post_event(q, "item_progress", id=item_id, percent=int(idx * 100 / total))

    if item_id:
        post_event(q, "item_progress", id=item_id, percent=100)
    post_event(q, "log", message=f"Extracted {written} files from {zip_path.name}")
    return written
