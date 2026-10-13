import hashlib
import queue
import shutil
import tempfile
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .download import (
    DownloadFailed,
    DownloadStopSignal,
    ItemControl,
    LinkExpiredError,
    download_with_progress,
    zip_is_readable,
)
from .events import EventThrottle, post_event
from .extract import safe_extract_zip
from .importer import find_memories_json
from .memories import MemoryEntry, build_id_index, load_memories, resolve_cdn_url
from .organize import Organizer
from .paths import get_script_paths
from .ratelimit import RateLimiter, RetryPolicy
from .settings import Settings
from .urls import get_zip_filename_from_url, is_export_zip_url, redact_url

MEMORIES_ITEM_ID = "memories"
EXPIRED_STREAK_LIMIT = 5

# Stage weights used for overall progress: (stage, start, end) per item kind.
STAGES = {
    "zip_url": {"download": (0.0, 0.6), "extract": (0.6, 0.8), "organize": (0.8, 1.0)},
    "zip_file": {"extract": (0.0, 0.5), "organize": (0.5, 1.0)},
    "folder": {"organize": (0.0, 1.0)},
    "memories": {"download": (0.0, 1.0)},
}


@dataclass
class Job:
    zip_urls: list[str] = field(default_factory=list)
    zip_files: list[Path] = field(default_factory=list)
    export_dirs: list[Path] = field(default_factory=list)
    memories_json: Path | None = None


@dataclass
class JobItem:
    id: str
    title: str
    kind: str
    source: str | Path


def plan_items(job: Job) -> list[JobItem]:
    items: list[JobItem] = []
    for url in job.zip_urls:
        name = get_zip_filename_from_url(url)
        items.append(JobItem(id=f"url:{name}", title=name, kind="zip_url", source=url))
    for p in job.zip_files:
        items.append(JobItem(id=f"zip:{p}", title=p.name, kind="zip_file", source=p))
    for d in job.export_dirs:
        items.append(JobItem(id=f"dir:{d}", title=f"{d.name} (folder)", kind="folder", source=d))
    if job.memories_json:
        items.append(JobItem(id=MEMORIES_ITEM_ID, title="Memories from memories_history.json", kind="memories", source=job.memories_json))
    return items


def memory_key(entry: MemoryEntry) -> str:
    ids = sorted(entry.ids)
    if ids:
        return ids[0]
    raw = f"{entry.date.isoformat()}|{entry.media_type}|{urllib.parse.urlsplit(entry.download_link).path}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def sniff_suffix(path: Path, kind: str) -> str:
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"PK\x03\x04"):
        return ".zip"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head[4:8] == b"ftyp":
        return ".mp4"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return ".webp"
    return ".mp4" if kind == "video" else ".jpg"


class JobRunner:
    def __init__(
        self,
        job: Job,
        settings: Settings,
        q: queue.Queue,
        stop_event: threading.Event,
        controls: dict[str, ItemControl] | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self.job = job
        self.settings = settings.normalized()
        self.q = q
        self.stop_event = stop_event
        self.items = plan_items(job)
        self.controls = controls or {}
        for it in self.items:
            self.controls.setdefault(it.id, ItemControl())
        self.policy = policy or RetryPolicy()
        self.paths = get_script_paths(self.settings.output_dir or None)
        self.limiter = RateLimiter.from_settings(self.settings.rate_limit_mb_s, self.settings.min_request_gap_ms)
        self.throttle = EventThrottle(0.25)
        self.summary = {"done": 0, "failed": 0, "expired": 0, "stopped": 0, "skipped": 0, "media": 0}

    def log(self, message: str) -> None:
        post_event(self.q, "log", message=message)

    def state(self, item: JobItem, state: str, detail: str = "") -> None:
        post_event(self.q, "item_state", id=item.id, state=state, detail=detail)

    def stage(self, item: JobItem, stage: str) -> None:
        post_event(self.q, "item_stage", id=item.id, stage=stage)
        post_event(self.q, "item_progress", id=item.id, percent=0)

    def run(self) -> dict:
        try:
            self._run()
        except DownloadStopSignal:
            self.stop_event.set()
        except Exception as e:
            if not self.stop_event.is_set():
                post_event(self.q, "error", message=f"Failed: {e}")
                return self.summary
        if self.stop_event.is_set():
            post_event(self.q, "done", ok=False, message="Cancelled.", summary=self.summary)
        else:
            s = self.summary
            parts = [f"{s['media']} media file(s) in {self.paths.media_dir}"]
            for key in ("failed", "expired", "stopped"):
                if s[key]:
                    parts.append(f"{s[key]} {key}")
            post_event(self.q, "done", ok=not (s["failed"] or s["expired"]), message="Finished: " + ", ".join(parts), summary=s)
        return self.summary

    def _run(self) -> None:
        self.paths.ensure()
        for it in self.items:
            post_event(self.q, "item_added", id=it.id, title=it.title, kind=it.kind)
            self.state(it, "queued")

        organizer = Organizer(
            self.paths.media_dir,
            layout=self.settings.layout,
            mode=self.settings.file_mode,
            q=self.q,
            stop_event=self.stop_event,
        )

        ready_zips: list[tuple[JobItem, Path]] = []
        url_items = [it for it in self.items if it.kind == "zip_url"]
        if url_items:
            ready_zips += self._download_zips(url_items)
        ready_zips += [(it, Path(it.source)) for it in self.items if it.kind == "zip_file"]

        extracted: list[tuple[JobItem, Path]] = []
        for it, zip_path in ready_zips:
            if self.stop_event.is_set():
                return
            if self.controls[it.id].stopped.is_set():
                self.state(it, "stopped")
                continue
            out_dir = self.paths.extracted_dir / zip_path.stem
            if out_dir.exists():
                shutil.rmtree(out_dir, ignore_errors=True)
            self.stage(it, "extract")
            self.state(it, "running", "Unzipping")
            try:
                safe_extract_zip(zip_path, out_dir, self.stop_event, self.q, item_id=it.id, throttle=self.throttle)
            except Exception as e:
                if self.stop_event.is_set():
                    return
                self.summary["failed"] += 1
                self.state(it, "failed", f"Unzip failed: {e}")
                continue
            extracted.append((it, out_dir))

        index_sources = [d for _, d in extracted] + [Path(it.source) for it in self.items if it.kind == "folder"]
        entries: list[MemoryEntry] = []
        for root in index_sources:
            found = find_memories_json(root)
            if found:
                try:
                    entries += load_memories(found)
                except (OSError, ValueError) as e:
                    self.log(f"Could not read {found.name}: {e}")
        organizer.id_index = build_id_index(entries)
        if entries:
            self.log(f"Using capture dates from memories_history.json ({len(entries)} entries)")

        for it, out_dir in extracted:
            self._organize(it, organizer, out_dir, mode=self.settings.file_mode)
            if self.settings.delete_extracted and not self.stop_event.is_set():
                shutil.rmtree(out_dir, ignore_errors=True)
        for it in (i for i in self.items if i.kind == "folder"):
            self._organize(it, organizer, Path(it.source), mode="copy")

        mem_item = next((i for i in self.items if i.kind == "memories"), None)
        if mem_item and not self.stop_event.is_set():
            self._download_memories(mem_item, organizer)

        organizer.write_index()
        self.summary["media"] = len(organizer.records)

    def _organize(self, it: JobItem, organizer: Organizer, root: Path, mode: str) -> None:
        if self.stop_event.is_set():
            return
        self.stage(it, "organize")
        self.state(it, "running", "Sorting media")
        organizer.mode = mode
        try:
            n = organizer.organize_tree(root, item_id=it.id)
        except Exception as e:
            if self.stop_event.is_set():
                return
            self.summary["failed"] += 1
            self.state(it, "failed", f"Sorting failed: {e}")
            return
        self.summary["done"] += 1
        post_event(self.q, "item_progress", id=it.id, percent=100)
        self.state(it, "done", f"{n} media file(s)")

    def _download_zips(self, items: list[JobItem]) -> list[tuple[JobItem, Path]]:
        ready: list[tuple[JobItem, Path]] = []
        with ThreadPoolExecutor(max_workers=self.settings.max_zip_downloads) as pool:
            futures = {pool.submit(self._download_one_zip, it): it for it in items}
            for fut in as_completed(futures):
                it = futures[fut]
                path = fut.result()
                if path is not None:
                    ready.append((it, path))
        order = {it.id: n for n, it in enumerate(items)}
        return sorted(ready, key=lambda pair: order[pair[0].id])

    def _download_one_zip(self, it: JobItem) -> Path | None:
        url = str(it.source)
        if not is_export_zip_url(url):
            self.summary["failed"] += 1
            self.state(it, "failed", "Not a Snapchat export link")
            self.log(f"Rejected link: {redact_url(url)}")
            return None
        dest = self.paths.downloads_dir / it.title
        self.stage(it, "download")
        self.state(it, "running", "Downloading")
        try:
            download_with_progress(
                url,
                dest,
                stop_event=self.stop_event,
                q=self.q,
                item_id=it.id,
                item=self.controls[it.id],
                limiter=self.limiter,
                policy=self.policy,
                throttle=self.throttle,
            )
        except DownloadStopSignal as e:
            if e.reason == "stop_item":
                self.summary["stopped"] += 1
                self.state(it, "stopped", "Stopped (partial file kept)")
            return None
        except LinkExpiredError as e:
            self.summary["expired"] += 1
            self.state(it, "expired", str(e))
            post_event(self.q, "links_expired", id=it.id)
            return None
        except Exception as e:
            self.summary["failed"] += 1
            self.state(it, "failed", str(e))
            return None
        return dest

    def _download_memories(self, it: JobItem, organizer: Organizer) -> None:
        try:
            entries = load_memories(Path(it.source))
        except (OSError, ValueError) as e:
            self.summary["failed"] += 1
            self.state(it, "failed", f"Could not read memories_history.json: {e}")
            return

        work_dir = self.paths.downloads_dir / "memories"
        work_dir.mkdir(parents=True, exist_ok=True)
        done_file = work_dir / "done.txt"
        done = set(done_file.read_text(encoding="utf-8").split()) if done_file.exists() else set()
        todo = [e for e in entries if memory_key(e) not in done]
        total = len(entries)
        completed = total - len(todo)
        failed = 0
        expired_streak = 0
        lock = threading.Lock()
        organizer.mode = "move"
        control = self.controls[it.id]

        self.stage(it, "download")
        self.state(it, "running", f"{completed}/{total} Memories")
        if not todo:
            post_event(self.q, "item_progress", id=it.id, percent=100, done_count=total, total_count=total)

        def fetch(entry: MemoryEntry) -> None:
            nonlocal completed, failed, expired_streak
            if expired_streak >= EXPIRED_STREAK_LIMIT:
                return
            key = memory_key(entry)
            try:
                self._fetch_memory(entry, key, work_dir, organizer, control, lock)
            except DownloadStopSignal:
                raise
            except LinkExpiredError:
                with lock:
                    expired_streak += 1
                    failed += 1
                return
            except Exception as e:
                with lock:
                    failed += 1
                self.log(f"Memory {entry.date:%Y-%m-%d %H:%M:%S}: {e}")
                return
            with lock:
                expired_streak = 0
                completed += 1
                with open(done_file, "a", encoding="utf-8") as f:
                    f.write(key + "\n")
                if self.throttle.ready(it.id) or completed == total:
                    post_event(
                        self.q,
                        "item_progress",
                        id=it.id,
                        percent=int(completed * 100 / total) if total else 100,
                        done_count=completed,
                        total_count=total,
                    )

        stopped = False
        with ThreadPoolExecutor(max_workers=self.settings.max_memory_downloads) as pool:
            futures = [pool.submit(fetch, e) for e in todo]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except DownloadStopSignal as e:
                    stopped = True
                    if e.reason == "stop_item":
                        control.stopped.set()
                    for f in futures:
                        f.cancel()

        if self.stop_event.is_set():
            return
        if expired_streak >= EXPIRED_STREAK_LIMIT:
            self.summary["expired"] += 1
            self.state(it, "expired", "The links in memories_history.json have expired. Request a new export.")
            post_event(self.q, "links_expired", id=it.id)
        elif stopped:
            self.summary["stopped"] += 1
            self.state(it, "stopped", f"{completed}/{total} Memories")
        elif failed:
            self.summary["failed"] += 1
            self.state(it, "failed", f"{completed}/{total} Memories, {failed} failed (run again to retry)")
        else:
            self.summary["done"] += 1
            self.state(it, "done", f"{completed}/{total} Memories")

    def _fetch_memory(
        self,
        entry: MemoryEntry,
        key: str,
        work_dir: Path,
        organizer: Organizer,
        control: ItemControl,
        lock: threading.Lock,
    ) -> None:
        tmp = work_dir / f"{key}.bin"
        common = dict(
            stop_event=self.stop_event,
            q=self.q,
            item=control,
            limiter=self.limiter,
            policy=self.policy,
            validate_zip=False,
        )
        try:
            cdn_url = resolve_cdn_url(entry, stop_event=self.stop_event, item=control, limiter=self.limiter, policy=self.policy)
            download_with_progress(cdn_url, tmp, **common)
        except DownloadFailed:
            download_with_progress(entry.download_link, tmp, headers={"X-Snap-Route-Tag": "mem-dmd"}, **common)

        suffix = sniff_suffix(tmp, entry.kind)
        if suffix == ".zip" and zip_is_readable(tmp):
            with tempfile.TemporaryDirectory(dir=work_dir) as td:
                safe_extract_zip(tmp, Path(td), self.stop_event, queue.Queue())
                with lock:
                    for f in sorted(Path(td).rglob("*")):
                        if f.is_file():
                            organizer.place(f, dt=entry.date, entry=entry)
            tmp.unlink(missing_ok=True)
            return
        final = tmp.with_suffix(suffix)
        tmp.replace(final)
        with lock:
            organizer.place(final, dt=entry.date, entry=entry)
