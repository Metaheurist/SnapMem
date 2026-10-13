"""
UI state for the Flet app. No Flet imports here: worker threads post events to
`self.q`, the UI calls `drain()` on its own loop and redraws whatever changed.
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import auth
from ..download import ItemControl
from ..events import post_event
from ..importer import ImportSelection, classify_inputs
from ..main import StartupOptions
from ..media import flatten_media_directory
from ..organize import MediaRecord, load_library, rebuild_index, reorganize_library
from ..paths import AppPaths, get_script_paths
from ..settings import Settings, load_settings, save_settings
from ..worker import STAGES, Job, JobRunner, plan_items

ACTIVE_STATES = {"queued", "running", "paused"}


@dataclass
class ItemView:
    id: str
    title: str
    kind: str
    state: str = "queued"
    detail: str = ""
    stage: str = ""
    percent: int = 0
    bytes: int = 0
    total_bytes: int | None = None
    rate_mb_s: float = 0.0
    done_count: int | None = None
    total_count: int | None = None

    @property
    def overall_fraction(self) -> float:
        if self.state in {"done", "skipped"}:
            return 1.0
        stages = STAGES.get(self.kind, {})
        start, end = stages.get(self.stage, (0.0, 1.0))
        return start + (end - start) * max(0, min(self.percent, 100)) / 100


class AppController:
    def __init__(self, opts: StartupOptions | None = None, settings: Settings | None = None) -> None:
        self.opts = opts or StartupOptions()
        self.settings = (settings or load_settings()).normalized()
        if self.opts.output_dir:
            self.settings.output_dir = self.opts.output_dir
        if self.opts.write_urls_file is not None:
            self.settings.write_urls_file = self.opts.write_urls_file
        self.q: queue.Queue = queue.Queue()
        self.urls: list[str] = list(self.opts.urls)
        self.selection = ImportSelection()
        self.items: dict[str, ItemView] = {}
        self.controls: dict[str, ItemControl] = {}
        self.logs: deque[str] = deque(maxlen=400)
        self.phase = "Ready"
        self.running = False
        self.auth_running = False
        self.auth_message = ""
        self.links_expired = False
        self.last_result: dict | None = None
        self.stop_event = threading.Event()
        self._auth_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.library_version = 0
        if self.opts.import_paths:
            self.add_import(self.opts.import_paths)

    # --- paths / settings -------------------------------------------------

    @property
    def paths(self) -> AppPaths:
        return get_script_paths(self.settings.output_dir or None)

    def update_settings(self, new: Settings) -> Settings:
        self.settings = new.normalized()
        save_settings(self.settings)
        self.log("Settings saved.")
        return self.settings

    def log(self, message: str) -> None:
        post_event(self.q, "log", message=message)

    # --- sign in ----------------------------------------------------------

    @property
    def has_saved_session(self) -> bool:
        return auth.has_saved_session()

    def sign_in(self) -> bool:
        if self.auth_running or self.running:
            return False
        self.auth_running = True
        self._auth_stop.clear()
        post_event(self.q, "auth_state", state="running", detail="Waiting for you to sign in in the browser window...")

        def run() -> None:
            urls_file = self.opts.urls_file or (self.paths.base_dir / "urls.txt")
            try:
                urls = auth.fetch_snapchat_export_urls(
                    urls_file,
                    min_urls=self.opts.min_urls,
                    timeout_sec=self.opts.timeout_sec,
                    write_urls_file=self.settings.write_urls_file,
                    keep_signed_in=self.settings.keep_signed_in,
                    log=self.log,
                    should_stop=self._auth_stop.is_set,
                )
            except Exception as e:
                post_event(self.q, "auth_state", state="failed", detail=str(e))
                return
            post_event(self.q, "links_found", urls=urls)
            post_event(self.q, "auth_state", state="done", detail=f"Found {len(urls)} export link(s).")

        threading.Thread(target=run, name="snapmem-auth", daemon=True).start()
        return True

    def cancel_sign_in(self) -> None:
        self._auth_stop.set()

    def sign_out(self) -> bool:
        removed = auth.sign_out()
        self.log("Signed out: saved browser session deleted." if removed else "No saved browser session to delete.")
        return removed

    # --- import -----------------------------------------------------------

    def add_import(self, paths: list[Path]) -> ImportSelection:
        picked = classify_inputs(list(paths))
        for p in picked.zip_files:
            if p not in self.selection.zip_files:
                self.selection.zip_files.append(p)
        for d in picked.export_dirs:
            if d not in self.selection.export_dirs:
                self.selection.export_dirs.append(d)
        if picked.memories_json:
            self.selection.memories_json = picked.memories_json
        for err in picked.errors:
            self.log(f"Import: {err}")
        return picked

    def clear_import(self) -> None:
        self.selection = ImportSelection()

    def clear_links(self) -> None:
        self.urls = []
        self.links_expired = False

    # --- job --------------------------------------------------------------

    def build_job(self) -> Job:
        return Job(
            zip_urls=list(self.urls),
            zip_files=list(self.selection.zip_files),
            export_dirs=list(self.selection.export_dirs),
            memories_json=self.selection.memories_json,
        )

    @property
    def can_start(self) -> bool:
        job = self.build_job()
        return not self.running and bool(job.zip_urls or job.zip_files or job.export_dirs or job.memories_json)

    def start(self) -> bool:
        if not self.can_start:
            return False
        job = self.build_job()
        self.items = {it.id: ItemView(id=it.id, title=it.title, kind=it.kind) for it in plan_items(job)}
        self.controls = {it_id: ItemControl() for it_id in self.items}
        self.stop_event = threading.Event()
        self.running = True
        self.links_expired = False
        self.last_result = None
        self.phase = "Working..."
        runner = JobRunner(job, self.settings, self.q, self.stop_event, controls=self.controls)
        self._worker = threading.Thread(target=runner.run, name="snapmem-job", daemon=True)
        self._worker.start()
        return True

    def cancel(self) -> None:
        if self.running:
            self.stop_event.set()
            self.phase = "Cancelling..."
            self.log("Cancel requested.")

    def toggle_pause(self, item_id: str) -> None:
        ctl = self.controls.get(item_id)
        view = self.items.get(item_id)
        if not ctl or not view or view.state not in ACTIVE_STATES:
            return
        if ctl.paused.is_set():
            ctl.paused.clear()
            view.state = "running"
        else:
            ctl.paused.set()
            view.state = "paused"

    def stop_item(self, item_id: str) -> None:
        ctl = self.controls.get(item_id)
        if ctl:
            ctl.paused.clear()
            ctl.stopped.set()

    @property
    def overall(self) -> float:
        if not self.items:
            return 0.0
        return sum(v.overall_fraction for v in self.items.values()) / len(self.items)

    # --- events -----------------------------------------------------------

    def apply_event(self, e: dict) -> set[str]:
        t = e.get("type")
        if t == "log":
            self.logs.append(str(e.get("message", "")))
            return {"logs"}
        if t == "phase":
            self.phase = str(e.get("text", ""))
            return {"status"}
        if t == "item_added":
            if e["id"] not in self.items:
                self.items[e["id"]] = ItemView(id=e["id"], title=e.get("title", e["id"]), kind=e.get("kind", ""))
            return {"items"}
        view = self.items.get(e.get("id", "")) if "id" in e else None
        if t == "item_stage" and view:
            view.stage = e.get("stage", "")
            view.percent = 0
            return {"items", "status"}
        if t == "item_progress" and view:
            view.percent = int(e.get("percent", view.percent) or 0)
            for key in ("bytes", "total_bytes", "rate_mb_s", "done_count", "total_count"):
                if key in e and e[key] is not None:
                    setattr(view, key, e[key])
            return {"items", "status"}
        if t == "item_state" and view:
            if not (view.state == "paused" and e.get("state") == "running"):
                view.state = e.get("state", view.state)
            view.detail = e.get("detail", "") or view.detail
            if view.state in {"done", "skipped"}:
                view.percent = 100
            return {"items", "status"}
        if t == "links_expired":
            self.links_expired = True
            return {"status", "links"}
        if t == "links_found":
            self.urls = list(e.get("urls", []))
            return {"links"}
        if t == "auth_state":
            state = e.get("state")
            self.auth_running = state == "running"
            self.auth_message = str(e.get("detail", ""))
            return {"auth"}
        if t == "done":
            self.running = False
            self.phase = str(e.get("message", "Done"))
            self.last_result = {"ok": bool(e.get("ok", True)), "message": self.phase, "summary": e.get("summary", {})}
            self.logs.append(self.phase)
            self.library_version += 1
            return {"status", "items", "logs", "library"}
        if t == "error":
            self.running = False
            self.phase = str(e.get("message", "Failed"))
            self.last_result = {"ok": False, "message": self.phase, "summary": {}}
            self.logs.append(self.phase)
            return {"status", "items", "logs"}
        if t == "library_changed":
            self.library_version += 1
            return {"library"}
        return set()

    def drain(self, max_events: int = 5000) -> set[str]:
        changed: set[str] = set()
        for _ in range(max_events):
            try:
                e = self.q.get_nowait()
            except queue.Empty:
                break
            changed |= self.apply_event(e)
        return changed

    # --- library ----------------------------------------------------------

    def library(self) -> list[MediaRecord]:
        return load_library(self.paths.media_dir)

    def _library_task(self, name: str, fn: Callable[[], str]) -> None:
        def run() -> None:
            try:
                self.log(fn())
            except Exception as e:
                self.log(f"{name} failed: {e}")
            post_event(self.q, "library_changed")

        threading.Thread(target=run, name=f"snapmem-{name}", daemon=True).start()

    def resort_library(self) -> bool:
        if self.running:
            return False
        media = self.paths.media_dir
        self._library_task("Re-sort", lambda: f"Re-sorted {reorganize_library(media, self.settings.layout)} file(s).")
        return True

    def flatten_library(self) -> bool:
        if self.running:
            return False
        media = self.paths.media_dir

        def run() -> str:
            moved, err = flatten_media_directory(media)
            if err:
                return err
            rebuild_index(media)
            return f"Flattened: moved {moved} file(s) into {media.name}/."

        self._library_task("Flatten", run)
        return True

    def clear_previous_data(self) -> bool:
        if self.running:
            return False
        p = self.paths
        for d in (p.downloads_dir, p.extracted_dir, p.media_dir):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
        self.items.clear()
        self.log("Cleared downloads/, extracted/ and media/.")
        post_event(self.q, "library_changed")
        return True

    def open_folder(self, path: Path | None = None) -> None:
        target = path or self.paths.media_dir
        if path is None:
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            return
        if sys.platform == "win32":
            os.startfile(str(target))  # nosec B606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])  # nosec B603 B607
        else:
            subprocess.Popen(["xdg-open", str(target)])  # nosec B603 B607
