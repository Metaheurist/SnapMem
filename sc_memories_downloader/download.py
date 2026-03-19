import queue
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .events import post_event


class DownloadStopSignal(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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

