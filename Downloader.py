import os
import sys
import argparse
import queue
import shutil
import threading
import time
import ctypes
import urllib.request
import urllib.parse
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText


# Hardcoded signed URLs removed.
# This script should always fetch fresh `mydata~*.zip` URLs via scraping (`Refresh URLs`).
URLS: list[str] = []
DEFAULT_URLS: list[str] = []

# Adjust this if you want more/less parallel downloads.
DOWNLOAD_WORKERS_DEFAULT = 4


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


@dataclass
class AppPaths:
    base_dir: Path
    downloads_dir: Path
    extracted_dir: Path
    media_dir: Path


class DownloadStopSignal(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def get_script_paths() -> AppPaths:
    # When running as a PyInstaller onefile EXE, `__file__` points inside the
    # temporary extraction directory. We want output folders to be created
    # next to the EXE (where the user launches it from).
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent
    downloads_dir = base_dir / "downloads"
    extracted_dir = base_dir / "extracted"
    media_dir = base_dir / "media"
    return AppPaths(base_dir=base_dir, downloads_dir=downloads_dir, extracted_dir=extracted_dir, media_dir=media_dir)


def setup_sc_dark_theme(style: ttk.Style, root: tk.Tk) -> None:
    """Apply a dark gray + yellow theme to ttk widgets."""
    # Windows ttk themes don't support every color property consistently,
    # but `clam` gives the best chance of getting the look we want.
    bg_root = "#1f1f1f"
    panel_bg = "#262626"
    panel_bg_2 = "#2f2f2f"
    fg = "#eaeaea"
    muted = "#cfcfcf"
    accent = "#f1c40f"  # SC-like yellow

    root.configure(bg=panel_bg)

    try:
        style.theme_use("clam")
    except tk.TclError:
        # Fall back to whatever theme is available.
        pass

    # Base widget styles.
    style.configure("TFrame", background=panel_bg)
    style.configure("TLabel", background=panel_bg, foreground=fg, font=("Segoe UI", 10))
    style.configure("TSeparator", background=panel_bg, foreground=panel_bg)

    # Buttons.
    style.configure(
        "TButton",
        background=panel_bg_2,
        foreground=fg,
        borderwidth=1,
        focusthickness=1,
        focuscolor=accent,
        padding=(10, 4),
    )
    style.map(
        "TButton",
        background=[("active", panel_bg_2), ("pressed", "#3a3a3a")],
        foreground=[("disabled", "#888888")],
    )

    # Progress bars.
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=panel_bg_2,
        background=accent,
        bordercolor=panel_bg_2,
        lightcolor=accent,
        darkcolor=accent,
    )

    # Treeview.
    style.configure(
        "Treeview",
        background=panel_bg_2,
        fieldbackground=panel_bg_2,
        foreground=fg,
        bordercolor=panel_bg_2,
        rowheight=22,
        font=("Segoe UI", 10),
    )
    style.configure(
        "Treeview.Heading",
        background=panel_bg,
        foreground=accent,
        relief="flat",
        font=("Segoe UI", 10, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", "#3a3a3a")],
        foreground=[("selected", fg)],
    )
    style.configure("Treeview.TScrollbar", background=bg_root)


def configure_window_behavior(root: tk.Tk) -> None:
    """Make the main window non-resizable and disable the maximize button (Windows).

    Note: removing the maximize box is done via a best-effort Windows style tweak.
    """
    try:
        root.resizable(False, False)
    except Exception:
        pass

    # Only supported on Windows.
    if sys.platform != "win32":
        return

    try:
        # Ensure the window handle exists.
        root.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()

        # Win32 style constants.
        GWL_STYLE = -16
        WS_MAXIMIZEBOX = 0x00010000

        # SetWindowPos flags.
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020

        style = int(user32.GetWindowLongW(hwnd, GWL_STYLE))
        new_style = style & ~WS_MAXIMIZEBOX
        if new_style != style:
            user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
    except Exception:
        # If anything fails, we still keep the window non-resizable via Tk.
        return


def post_event(q: queue.Queue, event_type: str, **payload) -> None:
    q.put({"type": event_type, **payload})


def get_zip_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name
    return name if name else "download.zip"


def load_urls() -> list[str]:
    """
    Optional `urls.txt` support:
    - If `urls.txt` (one URL per line) exists next to this script, use it.
    """
    urls_file = Path(__file__).resolve().parent / "urls.txt"
    if urls_file.exists():
        raw = urls_file.read_text(encoding="utf-8", errors="replace")
        urls = []
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            urls.append(s)
        if urls:
            return urls

    # No urls.txt present, and we intentionally do not embed any hardcoded signed URLs.
    return []


def load_urls_file(urls_file: Path) -> list[str]:
    if not urls_file.exists():
        return []
    raw = urls_file.read_text(encoding="utf-8", errors="replace")
    urls: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        urls.append(s)
    return urls


def configure_playwright_browsers_path() -> None:
    """Ensure Playwright can find Chromium browsers when bundled by PyInstaller.

    When running from a onefile EXE, PyInstaller extracts the bundled files to
    `sys._MEIPASS`. The build script can include Playwright browsers under a
    `playwright-browsers/` folder; we point Playwright to it via
    `PLAYWRIGHT_BROWSERS_PATH`.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if not getattr(sys, "frozen", False):
        return

    try:
        meipass = getattr(sys, "_MEIPASS", None)
        if not meipass:
            return
        base = Path(meipass)
        candidate = base / "playwright-browsers"
        if candidate.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
    except Exception:
        # Best-effort only; Playwright will fall back to its default paths.
        return


def fetch_snapchat_export_urls(
    urls_file: Path,
    min_urls: int = 5,
    timeout_sec: int = 300,
    write_urls_file: bool = False,
) -> list[str]:
    """
    Opens Snapchat "Download My Data" page, you log in, then we scrape
    `mydata~*.zip` hrefs.

    If `write_urls_file` is True, also saves them to `urls_file` (one URL per line).
    Requires Playwright + Chromium.
    """
    configure_playwright_browsers_path()
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except Exception:
        print(
            "playwright is required to fetch fresh Snapchat URLs.\n"
            "Install with:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium",
            file=sys.stderr,
        )
        raise

    SNAPCHAT_URL = "https://accounts.snapchat.com/v2/download-my-data"
    if write_urls_file:
        urls_file.parent.mkdir(parents=True, exist_ok=True)

    print("Opening Snapchat download page...")
    print("Please log in (MFA/captcha is fine). Waiting for export list...")

    def scrape_urls_from_page(page) -> list[str]:
        loc = page.locator('a[href*="mydata~"][href*=".zip"]')
        count = loc.count()
        if count == 0:
            return []
        urls = loc.evaluate_all('els => els.map(e => e.getAttribute("href")).filter(Boolean)')
        cleaned: list[str] = []
        for u in urls:
            s = str(u).strip()
            if "storage.googleapis.com" in s and "mydata~" in s and ".zip" in s:
                cleaned.append(s)

        # Deduplicate while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for s in cleaned:
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(SNAPCHAT_URL, wait_until="domcontentloaded")

        start = time.time()
        urls: list[str] = []

        while time.time() - start < timeout_sec:
            # If exports are collapsed, try expanding.
            try:
                btn = page.locator('button:has-text("Show exports")')
                if btn.count() > 0:
                    btn.first.click()
            except Exception:
                pass

            page.wait_for_timeout(1000)
            urls = scrape_urls_from_page(page)
            if len(urls) >= min_urls:
                break

        browser.close()

    if not urls:
        raise RuntimeError("No download ZIP URLs found. Make sure the exports list is visible.")

    if write_urls_file:
        urls_file.write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"Saved {len(urls)} URLs to: {urls_file}")
    else:
        print(f"Scraped {len(urls)} URLs.")
    return urls


def download_with_progress(
    url: str,
    dest_path: Path,
    stop_event: threading.Event,
    item_pause_event: threading.Event,
    item_stop_event: threading.Event,
    q: queue.Queue,
    current_index: int,
    total: int,
) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")

    def zip_looks_valid(p: Path) -> bool:
        try:
            # Opening the ZIP validates headers without extracting.
            with zipfile.ZipFile(p, "r") as zf:
                return zf.testzip() is None
        except Exception:
            return False

    if dest_path.exists() and dest_path.stat().st_size > 0:
        if zip_looks_valid(dest_path):
            post_event(q, "log", message=f"Skipping already-downloaded: {dest_path.name}")
            post_event(
                q,
                "current_progress",
                index=current_index,
                percent=100,
                bytes_downloaded=dest_path.stat().st_size,
                rate_mb_s=0.0,
            )
            return
        # Remove bad/incomplete file so we can re-download cleanly.
        try:
            dest_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Resume support:
    # - If a partial download exists from a prior run, resume from its byte size.
    # - Keying is based on the destination ZIP filename, so refreshed URLs with the same
    #   filename still resume correctly.
    resume_offset = 0
    if part_path.exists():
        try:
            resume_offset = max(0, int(part_path.stat().st_size))
        except Exception:
            resume_offset = 0

    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Downloader.py",
        "Accept": "*/*",
    }
    if resume_offset > 0:
        headers["Range"] = f"bytes={resume_offset}-"

    req = urllib.request.Request(url, headers=headers)
    post_event(q, "set_phase", text=f"Downloading {current_index}/{total}")

    try:
        with urllib.request.urlopen(req) as resp:
            remaining_len_hdr = resp.headers.get("Content-Length")
            remaining_len = int(remaining_len_hdr) if remaining_len_hdr and remaining_len_hdr.isdigit() else None

            # Try to get original total from Content-Range when resuming.
            content_range = resp.headers.get("Content-Range")  # e.g. "bytes 100-999/2000"
            total_bytes: int | None = None
            if content_range and "/" in content_range:
                try:
                    after_slash = content_range.split("/", 1)[1].strip()
                    if after_slash.isdigit():
                        total_bytes = int(after_slash)
                except Exception:
                    total_bytes = None

            # If server ignored Range and returned full content (200), restart from scratch.
            status_code = getattr(resp, "status", None) or resp.getcode()
            resume_used = resume_offset > 0 and status_code == 206
            if resume_offset > 0 and status_code != 206:
                resume_offset = 0
                resume_used = False
                total_bytes = remaining_len  # treat as full file now
            if resume_offset == 0 and total_bytes is None:
                # Not resuming (or Range ignored): Content-Length is the total.
                total_bytes = remaining_len

            downloaded = resume_offset
            start_time = time.time()
            last_emit_time = start_time
            last_emit_bytes = downloaded

            chunk_size = 1024 * 256  # 256 KB
            open_mode = "ab" if resume_offset > 0 and resume_used else "wb"
            with open(part_path, open_mode) as f:
                while True:
                    if stop_event.is_set():
                        raise DownloadStopSignal("cancel_all")
                    if item_stop_event.is_set():
                        raise DownloadStopSignal("stop_item")

                    # Pause support: when paused, cooperatively wait between reads.
                    while not item_pause_event.is_set():
                        if stop_event.is_set():
                            raise DownloadStopSignal("cancel_all")
                        if item_stop_event.is_set():
                            raise DownloadStopSignal("stop_item")
                        item_pause_event.wait(timeout=0.5)

                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    # Emit at most ~2 times/sec to keep the UI responsive.
                    if now - last_emit_time >= 0.5:
                        elapsed = now - last_emit_time
                        rate_mb_s = (downloaded - last_emit_bytes) / elapsed / (1024 * 1024) if elapsed > 0 else 0.0

                        if total_bytes and total_bytes > 0:
                            percent = int(downloaded * 100 / total_bytes)
                            percent = max(0, min(100, percent))
                        else:
                            # Fallback if Content-Length isn't provided.
                            percent = 0

                        post_event(
                            q,
                            "current_progress",
                            index=current_index,
                            percent=percent,
                            bytes_downloaded=downloaded,
                            rate_mb_s=rate_mb_s,
                            total_bytes=total_bytes,
                        )

                        last_emit_time = now
                        last_emit_bytes = downloaded
    except urllib.error.HTTPError as e:
        post_event(q, "current_progress", index=current_index, percent=0, bytes_downloaded=0, rate_mb_s=0.0)
        post_event(q, "log", message=f"HTTP {e.code} downloading {dest_path.name}: {getattr(e, 'reason', '')}")
        try:
            body = e.read(1500)
            if body:
                decoded = body.decode("utf-8", "replace")
                # Keep log readable.
                post_event(q, "log", message=f"Server response: {decoded[:900]}")
        except Exception:
            pass
        try:
            part_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    except DownloadStopSignal:
        post_event(q, "download_stopped", index=current_index)
        raise
    except Exception:
        try:
            part_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    # Finalize download.
    part_path.replace(dest_path)
    post_event(q, "current_progress", index=current_index, percent=100, bytes_downloaded=dest_path.stat().st_size, rate_mb_s=0.0)
    post_event(q, "log", message=f"Downloaded: {dest_path.name}")


def safe_extract_zip(zip_path: Path, extract_to: Path, stop_event: threading.Event, q: queue.Queue, phase_prefix: str) -> None:
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


def copy_media_from_tree(root_dir: Path, destination_dir: Path, stop_event: threading.Event, q: queue.Queue, phase_text: str) -> int:
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


def worker_main(
    urls: list[str],
    stop_event: threading.Event,
    item_pause_events: dict[int, threading.Event],
    item_stop_events: dict[int, threading.Event],
    q: queue.Queue,
) -> None:
    paths = get_script_paths()
    # Ensure output directory tree exists in the current app location.
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    paths.downloads_dir.mkdir(parents=True, exist_ok=True)
    paths.extracted_dir.mkdir(parents=True, exist_ok=True)
    paths.media_dir.mkdir(parents=True, exist_ok=True)

    total = len(urls)
    post_event(q, "overall_progress", percent=0)
    post_event(q, "set_phase", text="Preparing")

    try:
        # Stage 1: download all zips in parallel (unzipping is done after).
        # Download all ZIPs concurrently (as requested).
        download_workers = total if total else 1
        post_event(q, "set_phase", text=f"Downloading in parallel (x{download_workers})...")

        items: list[tuple[int, str, Path, Path]] = []
        for i, url in enumerate(urls, start=1):
            zip_name = get_zip_filename_from_url(url)
            zip_path = paths.downloads_dir / zip_name
            extract_to = paths.extracted_dir / zip_name.replace(".zip", "")
            items.append((i, zip_name, zip_path, extract_to))

        post_event(q, "overall_progress", percent=0)

        failed_exc: Exception | None = None
        stopped_count = 0
        with ThreadPoolExecutor(max_workers=download_workers) as executor:
            futures = {}
            for i, zip_name, zip_path, extract_to in items:
                post_event(q, "log", message=f"[{i}/{total}] {zip_name}")
                futures[
                    executor.submit(
                        download_with_progress,
                        urls[i - 1],
                        zip_path,
                        stop_event,
                        item_pause_events[i],
                        item_stop_events[i],
                        q,
                        i,
                        total,
                    )
                ] = (i, zip_name)

            completed_downloads = 0
            for fut in as_completed(futures):
                if stop_event.is_set():
                    break
                try:
                    fut.result()
                except DownloadStopSignal as e:
                    if e.reason == "cancel_all":
                        stop_event.set()
                        break
                    # stop_item: continue with other downloads
                    stopped_count += 1
                    continue
                except Exception as e:
                    failed_exc = e
                    stop_event.set()
                    # Let other threads notice cancellation.
                    break
                completed_downloads += 1
                post_event(q, "overall_progress", percent=int(completed_downloads * 50 / total) if total else 50)

        if failed_exc:
            raise failed_exc

        # Stage 2: unzip + collect media sequentially per zip.
        post_event(q, "set_phase", text="Unzipping + collecting media...")
        for i, url in enumerate(urls, start=1):
            zip_name = get_zip_filename_from_url(url)
            zip_path = paths.downloads_dir / zip_name
            extract_to = paths.extracted_dir / zip_name.replace(".zip", "")

            # If a ZIP was stopped/cancelled, it may not exist or may be incomplete.
            if not zip_path.exists() or zip_path.stat().st_size <= 0:
                post_event(q, "log", message=f"Skipping unzip (missing): {zip_name}")
                continue
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if zf.testzip() is not None:
                        post_event(q, "log", message=f"Skipping unzip (invalid ZIP): {zip_name}")
                        continue
            except Exception:
                post_event(q, "log", message=f"Skipping unzip (ZIP check failed): {zip_name}")
                continue

            # Clean extract destination if it exists (ensures consistency on reruns)
            if extract_to.exists():
                shutil.rmtree(extract_to, ignore_errors=True)

            post_event(q, "log", message=f"Unzipping: {zip_name}")
            safe_extract_zip(zip_path, extract_to, stop_event, q, phase_prefix="Unzipping")

            post_event(q, "log", message=f"Collecting media from: {zip_name}")
            media_subdir = paths.media_dir / zip_name.replace(".zip", "")
            copy_media_from_tree(extract_to, media_subdir, stop_event, q, phase_text="Collecting media")

            post_event(q, "overall_progress", percent=50 + int(i * 50 / total) if total else 100)

        if stopped_count > 0:
            post_event(
                q,
                "done",
                message=f"All done (but {stopped_count} ZIP(s) were stopped/unfinished). Media saved to: {paths.media_dir}",
            )
        else:
            post_event(q, "done", message=f"All done. Media saved to: {paths.media_dir}")

    except Exception as e:
        if stop_event.is_set():
            post_event(q, "done", message="Cancelled.")
        else:
            post_event(q, "error", message=f"Failed: {e}")


class DownloaderUI:
    def __init__(
        self,
        root: tk.Tk,
        urls: list[str],
        urls_file: Path,
        min_urls: int,
        timeout_sec: int,
        write_urls_file: bool,
    ):
        self.root = root
        self.urls = urls
        self.urls_file = urls_file
        self.min_urls = min_urls
        self.timeout_sec = timeout_sec
        self.write_urls_file = write_urls_file
        self.refresh_retry_count = 0
        self.refresh_retry_max = 3

        self.stop_event = threading.Event()
        self.q: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.progress_by_index: dict[int, float] = {}
        self.item_pause_events: dict[int, threading.Event] = {}
        self.item_stop_events: dict[int, threading.Event] = {}
        self.item_paused: dict[int, bool] = {}
        self.item_stopped: dict[int, bool] = {}

        root.title("SC Memories Downloader (ZIP + Unzip + Media Collector)")
        root.geometry("920x620")
        configure_window_behavior(root)

        # Ensure the main background is consistent even for non-ttk widgets.
        try:
            self.root.configure(bg="#262626")
        except Exception:
            pass

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Ready")
        self.phase_var = tk.StringVar(value="Idle")

        ttk.Label(frm, text="Status:").grid(row=0, column=0, sticky="w")
        ttk.Label(frm, textvariable=self.status_var).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Phase:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(frm, textvariable=self.phase_var).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Separator(frm).grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)

        ttk.Label(frm, text="Current progress:").grid(row=3, column=0, sticky="w")
        self.current_percent_var = tk.StringVar(value="0%")
        self.current_pb_frame = ttk.Frame(frm, width=520, height=20)
        self.current_pb_frame.grid(row=3, column=1, sticky="w", pady=(2, 0))

        self.current_pb = ttk.Progressbar(self.current_pb_frame, length=520, mode="determinate", maximum=100)
        self.current_pb.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)

        # ttk.Progressbar can't show text, so we overlay a label in the middle.
        self.current_percent_label = tk.Label(
            self.current_pb_frame,
            textvariable=self.current_percent_var,
            bg="#262626",
            fg="#f1c40f",
            font=("Segoe UI", 10, "bold"),
        )
        self.current_percent_label.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(frm, text="Overall zips:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.overall_pb = ttk.Progressbar(frm, length=520, mode="determinate", maximum=100)
        self.overall_pb.grid(row=4, column=1, sticky="w", pady=(8, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

        self.clear_btn = ttk.Button(btns, text="Clear previous data", command=self.clear_previous_data)
        self.clear_btn.pack(side="left")

        self.refresh_btn = ttk.Button(btns, text="Refresh URLs", command=self.refresh_urls)
        self.refresh_btn.pack(side="left", padx=(8, 0))

        self.start_btn = ttk.Button(btns, text="Start", command=self.start)
        self.start_btn.pack(side="left")

        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))

        ttk.Label(frm, text="Download progress per ZIP: (pause/resume/stop in Control column)").grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 0))

        # Treeview can't embed real ttk.Button widgets per-row; instead we render clickable icons
        # in the "control" column. Click left half to pause/resume, right half to stop.
        self.tree = ttk.Treeview(
            frm,
            columns=("name", "progress", "mb", "rate", "control"),
            show="headings",
            height=7,
        )
        self.tree.heading("name", text="ZIP")
        self.tree.heading("progress", text="%")
        self.tree.heading("mb", text="MB")
        self.tree.heading("rate", text="MB/s")
        self.tree.heading("control", text="Control")
        self.tree.column("name", width=500, stretch=True, anchor="w")
        self.tree.column("progress", width=70, stretch=False, anchor="e")
        self.tree.column("mb", width=110, stretch=False, anchor="e")
        self.tree.column("rate", width=110, stretch=False, anchor="e")
        self.tree.column("control", width=120, stretch=False, anchor="center")
        self.tree.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # Map 1-based index -> tree iid (string)
        self.zip_names_by_index: dict[int, str] = {
            i: get_zip_filename_from_url(urls[i - 1]) for i in range(1, len(urls) + 1)
        }

        for i, zip_name in self.zip_names_by_index.items():
            iid = str(i)
            self.tree.insert("", "end", iid=iid, values=(zip_name, "0%", "0.00 MB", "0.00 MB/s", "||  X"))

        if not urls:
            # Without URLs (hardcoded defaults removed), user must refresh URLs after login/auth.
            self.start_btn.config(state="disabled")
            self.status_var.set("No URLs. Click 'Refresh URLs' to login/auth.")
            self.phase_var.set("Idle")

        # Enable clicking on the control column.
        self.tree.bind("<Button-1>", self.on_tree_click)

        self.log = ScrolledText(frm, height=14, wrap="word")
        # Match the dark theme log styling.
        try:
            self.log.configure(bg="#1f1f1f", fg="#eaeaea", insertbackground="#f1c40f")
        except Exception:
            pass
        self.log.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        frm.rowconfigure(8, weight=1)
        frm.columnconfigure(1, weight=1)

        self.poll_queue()

    def log_line(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{ts}] {msg}\n")
        self.log.see("end")

    def on_tree_click(self, event: tk.Event) -> None:
        """Handle clicks on the Treeview 'control' column.

        Treeview doesn't support real buttons per row, so we interpret the click:
        - click left half in the control cell: pause/resume
        - click right half in the control cell: stop that download
        """
        try:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            idx = int(iid)

            columns = list(self.tree["columns"])
            control_col = "control"
            if control_col not in columns:
                return
            control_col_no = columns.index(control_col) + 1
            col = self.tree.identify_column(event.x)
            if col != f"#{control_col_no}":
                return

            bbox = self.tree.bbox(iid, control_col)
            if not bbox:
                return
            x0, _y0, w, _h = bbox

            if idx not in self.item_pause_events or idx not in self.item_stop_events:
                return  # downloads not started yet
            if self.item_stopped.get(idx, False):
                return

            # Left half => pause/resume. Right half => stop.
            if event.x < x0 + w / 2:
                self.toggle_item_pause(idx)
            else:
                self.stop_item_download(idx)
        except Exception:
            # Never let UI click handling crash the app.
            return

    def toggle_item_pause(self, idx: int) -> None:
        paused = self.item_paused.get(idx, False)
        if paused:
            # Resume
            self.item_pause_events[idx].set()
            self.item_paused[idx] = False
            if self.tree.exists(str(idx)):
                self.tree.set(str(idx), "control", "||  X")
            self.log_line(f"Resumed: {self.tree.set(str(idx), 'name')}")
        else:
            # Pause
            self.item_pause_events[idx].clear()
            self.item_paused[idx] = True
            if self.tree.exists(str(idx)):
                self.tree.set(str(idx), "control", ">   X")
            self.log_line(f"Paused: {self.tree.set(str(idx), 'name')}")

    def stop_item_download(self, idx: int) -> None:
        if self.item_stopped.get(idx, False):
            return
        self.item_stop_events[idx].set()
        self.item_stopped[idx] = True
        # Stop icon state.
        if self.tree.exists(str(idx)):
            self.tree.set(str(idx), "control", "X")
        self.log_line(f"Stopped: {self.tree.set(str(idx), 'name')}")

    def start(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        self.clear_btn.config(state="disabled")
        self.progress_by_index = {i: 0.0 for i in range(1, len(self.urls) + 1)}

        # Per-download pause/stop signals.
        self.item_pause_events = {i: threading.Event() for i in range(1, len(self.urls) + 1)}
        self.item_stop_events = {i: threading.Event() for i in range(1, len(self.urls) + 1)}
        for i in self.item_pause_events:
            self.item_pause_events[i].set()  # allow running
            self.item_stop_events[i].clear()
        self.item_paused = {i: False for i in range(1, len(self.urls) + 1)}
        self.item_stopped = {i: False for i in range(1, len(self.urls) + 1)}

        for i in range(1, len(self.urls) + 1):
            iid = str(i)
            if self.tree.exists(iid):
                self.tree.set(iid, "progress", "0%")
                self.tree.set(iid, "mb", "0.00 MB")
                self.tree.set(iid, "rate", "0.00 MB/s")
                self.tree.set(iid, "control", "||  X")
        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.status_var.set("Running")
        self.phase_var.set("Starting...")
        self.log_line("Starting downloads...")

        self.worker_thread = threading.Thread(
            target=worker_main,
            args=(self.urls, self.stop_event, self.item_pause_events, self.item_stop_events, self.q),
            daemon=True,
        )
        self.worker_thread.start()

    def apply_new_urls(self, urls: list[str]) -> None:
        """Replace current URL set and update the ZIP list."""
        self.urls = urls

        # Reset progress tracking.
        self.progress_by_index = {i: 0.0 for i in range(1, len(self.urls) + 1)}

        # Clear and repopulate the table.
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        self.zip_names_by_index = {
            i: get_zip_filename_from_url(urls[i - 1]) for i in range(1, len(urls) + 1)
        }
        for i, zip_name in self.zip_names_by_index.items():
            iid = str(i)
            self.tree.insert("", "end", iid=iid, values=(zip_name, "0%", "0.00 MB", "0.00 MB/s", "||  X"))

        self.current_pb["value"] = 0
        self.overall_pb["value"] = 0
        if hasattr(self, "current_percent_var"):
            self.current_percent_var.set("0%")

        if not self.urls:
            self.start_btn.config(state="disabled")
            self.status_var.set("No URLs. Click 'Refresh URLs' to login/auth.")
            self.phase_var.set("Idle")
        else:
            self.start_btn.config(state="normal")
            self.status_var.set("Ready")
            self.phase_var.set("Idle")

    def refresh_urls(self) -> None:
        """Scrape fresh Snapchat URLs in a background thread."""
        if self.worker_thread and self.worker_thread.is_alive():
            return

        # Disable buttons while scraping to avoid concurrent operations.
        self.refresh_btn.config(state="disabled")
        self.clear_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")

        self.status_var.set("Refreshing URLs")
        self.phase_var.set("Scraping Snapchat download page...")
        self.log_line("Refreshing URLs... (log in + wait for exports list)")

        def run() -> None:
            try:
                urls = fetch_snapchat_export_urls(
                    self.urls_file,
                    min_urls=self.min_urls,
                    timeout_sec=self.timeout_sec,
                    write_urls_file=self.write_urls_file,
                )
                post_event(self.q, "urls_refreshed", urls=urls)
            except Exception as e:
                post_event(self.q, "urls_refresh_failed", error=str(e))

        threading.Thread(target=run, daemon=True).start()

    def cancel(self) -> None:
        self.stop_event.set()
        self.status_var.set("Cancelling...")
        self.phase_var.set("Cancelling...")
        self.log_line("Cancel requested.")

    def clear_previous_data(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        if not messagebox.askyesno("Confirm", "Delete previous contents of downloads/, extracted/, and media/?"):
            return

        paths = get_script_paths()
        for d in (paths.downloads_dir, paths.extracted_dir, paths.media_dir):
            try:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                d.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.log_line(f"Clear failed for {d.name}: {e}")
                continue

        self.log_line("Cleared previous data folders.")

    def poll_queue(self) -> None:
        try:
            while True:
                event = self.q.get_nowait()
                etype = event.get("type")
                if etype == "log":
                    self.log_line(event.get("message", ""))
                elif etype == "set_phase":
                    self.phase_var.set(event.get("text", ""))
                elif etype == "current_progress":
                    percent = float(event.get("percent", 0))
                    idx = event.get("index")
                    if idx is None:
                        # Extraction phase sends a single global progress value.
                        self.current_pb["value"] = percent
                        self.current_percent_var.set(f"{percent:.0f}%")
                    else:
                        # Download phase sends per-zip progress; show the average.
                        idx_i = int(idx)
                        self.progress_by_index[idx_i] = percent
                        iid = str(idx_i)
                        if self.tree.exists(iid):
                            bytes_downloaded = event.get("bytes_downloaded")
                            rate_mb_s = event.get("rate_mb_s", 0.0)
                            if isinstance(bytes_downloaded, (int, float)) and bytes_downloaded >= 0:
                                mb_downloaded = bytes_downloaded / (1024 * 1024)
                            else:
                                mb_downloaded = 0.0

                            self.tree.set(iid, "progress", f"{percent:.0f}%")
                            self.tree.set(iid, "mb", f"{mb_downloaded:.2f} MB")
                            self.tree.set(iid, "rate", f"{float(rate_mb_s):.2f} MB/s")
                        if self.progress_by_index:
                            avg = sum(self.progress_by_index.values()) / len(self.progress_by_index)
                            self.current_pb["value"] = avg
                            self.current_percent_var.set(f"{avg:.0f}%")
                elif etype == "overall_progress":
                    self.overall_pb["value"] = float(event.get("percent", 0))
                elif etype == "done":
                    self.status_var.set("Done")
                    self.phase_var.set("Idle")
                    self.cancel_btn.config(state="disabled")
                    msg = event.get("message", "Done.")
                    self.log_line(msg)
                elif etype == "download_stopped":
                    idx = event.get("index")
                    if idx is not None:
                        idx_i = int(idx)
                        self.item_stopped[idx_i] = True
                        self.item_paused[idx_i] = False
                        if self.tree.exists(str(idx_i)):
                            self.tree.set(str(idx_i), "control", "X")
                        self.log_line(f"Stopped ZIP #{idx_i}")
                elif etype == "urls_refreshed":
                    urls = event.get("urls", []) or []
                    if not urls:
                        self.status_var.set("Error")
                        self.phase_var.set("Idle")
                        self.refresh_btn.config(state="normal")
                        self.clear_btn.config(state="normal")
                        self.start_btn.config(state="disabled")
                        self.log_line("Refresh completed but no URLs were found.")
                    else:
                        self.refresh_retry_count = 0
                        self.apply_new_urls(urls)
                        self.status_var.set("Ready")
                        self.phase_var.set("Idle")
                        self.refresh_btn.config(state="normal")
                        self.clear_btn.config(state="normal")
                        self.start_btn.config(state="normal")
                        self.log_line(f"Refreshed {len(urls)} URLs.")
                elif etype == "urls_refresh_failed":
                    err = event.get("error", "Refresh failed.")
                    self.status_var.set("Error")
                    self.phase_var.set("Idle")
                    self.refresh_btn.config(state="normal")
                    self.clear_btn.config(state="normal")
                    self.start_btn.config(state="disabled")
                    self.log_line(f"URL refresh failed: {err}")

                    # Most common case: user hasn't completed login/MFA/captcha or exports are not visible yet.
                    needs_reauth = ("No download ZIP URLs found" in err) or ("Make sure the exports list is visible" in err)
                    if needs_reauth and self.refresh_retry_count < self.refresh_retry_max:
                        retry = messagebox.askyesno(
                            "Login/Auth needed",
                            "I couldn't find the export ZIP links.\n\n"
                            "Please complete login/MFA/captcha in the browser window that opened, then click Yes to retry refreshing URLs.",
                        )
                        if retry:
                            self.refresh_retry_count += 1
                            self.refresh_urls()
                elif etype == "error":
                    self.status_var.set("Error")
                    self.phase_var.set("Idle")
                    self.cancel_btn.config(state="disabled")
                    self.refresh_btn.config(state="normal")
                    self.clear_btn.config(state="normal")
                    self.start_btn.config(state="normal")
                    self.log_line(event.get("message", "Error"))
                else:
                    # Unknown event: ignore
                    pass
        except queue.Empty:
            pass

        self.root.after(200, self.poll_queue)


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapchat memories downloader (download + unzip + media collector)")
    parser.add_argument(
        "--fetch-urls",
        action="store_true",
        help="Deprecated: URLs are refreshed on each run by default. Use --skip-fetch-urls to avoid scraping.",
    )
    parser.add_argument(
        "--skip-fetch-urls",
        action="store_true",
        help="Skip Playwright scraping and use urls.txt (or built-in hardcoded URLs).",
    )
    parser.add_argument(
        "--urls-file",
        default=str(Path(__file__).resolve().parent / "urls.txt"),
        help="Where to read/write ZIP URLs (default: urls.txt next to script).",
    )
    parser.add_argument(
        "--write-urls-file",
        action="store_true",
        help="Store scraped signed URLs into urls.txt (contains identifiable signed links). Default: off.",
    )
    parser.add_argument("--min-urls", type=int, default=5, help="Minimum URLs to wait for when --fetch-urls is used.")
    parser.add_argument("--timeout-sec", type=int, default=300, help="Timeout (seconds) for --fetch-urls.")
    args = parser.parse_args()

    urls_file = Path(args.urls_file)
    urls: list[str] = []

    if not args.skip_fetch_urls:
        try:
            urls = fetch_snapchat_export_urls(
                urls_file,
                min_urls=args.min_urls,
                timeout_sec=args.timeout_sec,
                write_urls_file=args.write_urls_file,
            )
        except Exception as e:
            print(
                f"Warning: URL refresh on startup failed: {e}\n"
                f"Starting with urls.txt (if present). Click 'Refresh URLs' to re-login/auth and regenerate signed links.",
                file=sys.stderr,
            )
            urls = load_urls_file(urls_file)
            if not urls:
                urls = load_urls()
    else:
        urls = load_urls_file(urls_file)
        if not urls:
            urls = load_urls()

    root = tk.Tk()
    style = ttk.Style(root)
    setup_sc_dark_theme(style, root)

    ui = DownloaderUI(
        root,
        urls,
        urls_file=urls_file,
        min_urls=args.min_urls,
        timeout_sec=args.timeout_sec,
        write_urls_file=args.write_urls_file,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
