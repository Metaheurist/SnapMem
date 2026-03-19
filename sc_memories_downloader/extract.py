import queue
import threading
import zipfile
from pathlib import Path

from .events import post_event


def safe_extract_zip(
    zip_path: Path,
    extract_to: Path,
    stop_event: threading.Event,
    q: queue.Queue,
    phase_prefix: str,
) -> None:
    extract_to.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total = len(members)

        # Normalize for “zip slip” protection
        base_resolved = extract_to.resolve()

        for idx, m in enumerate(members, start=1):
            if stop_event.is_set():
                raise RuntimeError("Cancelled")

            # Skip weird entries safely
            name = m.filename
            if not name or name.endswith("/"):
                # Directory entry
                target = (extract_to / name).resolve() if name else extract_to.resolve()
                if str(target).startswith(str(base_resolved)):
                    target.mkdir(parents=True, exist_ok=True)
                continue

            target = (extract_to / name).resolve()
            if not str(target).startswith(str(base_resolved)):
                post_event(q, "log", message=f"Skipped unsafe path in zip: {name}")
                continue

            # Update progress
            percent = int(idx * 100 / total) if total else 100
            post_event(q, "current_progress", percent=percent)

            # Ensure parent dir exists
            target.parent.mkdir(parents=True, exist_ok=True)

            # Extract safely (we validated target is within base_resolved)
            zf.extract(m, path=str(extract_to))

    post_event(q, "current_progress", percent=100)
    post_event(q, "log", message=f"Extracted: {zip_path.name}")

