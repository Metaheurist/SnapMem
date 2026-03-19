import queue
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .download import DownloadStopSignal, download_with_progress
from .events import post_event
from .extract import safe_extract_zip
from .media import copy_media_from_tree
from .paths import get_script_paths
from .urls import get_zip_filename_from_url


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

