import http.client
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .events import EventThrottle, post_event
from .ratelimit import RateLimiter, RetryPolicy, parse_retry_after
from .urls import redact_text

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SnapMem"
CHUNK_SIZE = 256 * 1024
DEFAULT_TIMEOUT = 30.0

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}
EXPIRED_STATUS = {401, 403, 410}
TRANSIENT_ERRORS = (
    urllib.error.URLError,
    ConnectionError,
    TimeoutError,
    socket.timeout,
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
)


class DownloadStopSignal(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LinkExpiredError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"Link expired or no longer authorised (HTTP {status}). Refresh the export links.")
        self.status = status


class DownloadFailed(Exception):
    pass


@dataclass
class ItemControl:
    """Per-item pause/stop flags shared between the UI and one download thread."""

    paused: threading.Event = field(default_factory=threading.Event)
    stopped: threading.Event = field(default_factory=threading.Event)


def check_stop(stop_event: threading.Event, item: ItemControl | None = None) -> None:
    if stop_event.is_set():
        raise DownloadStopSignal("cancel_all")
    if item is None:
        return
    if item.stopped.is_set():
        raise DownloadStopSignal("stop_item")
    while item.paused.is_set():
        if stop_event.is_set():
            raise DownloadStopSignal("cancel_all")
        if item.stopped.is_set():
            raise DownloadStopSignal("stop_item")
        time.sleep(0.25)


def _allow_http(host: str) -> bool:
    """Plain http is only accepted for loopback (local test servers)."""
    hostname = (host or "").rsplit(":", 1)[0].strip("[]").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def interruptible_sleep(seconds: float, stop_event: threading.Event, item: ItemControl | None = None) -> None:
    deadline = time.monotonic() + seconds
    while True:
        check_stop(stop_event, item)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        stop_event.wait(timeout=min(0.25, remaining))


def zip_is_readable(path: Path) -> bool:
    """Opens only the central directory, so it stays fast on multi-GB ZIPs."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return bool(zf.infolist())
    except (OSError, zipfile.BadZipFile, ValueError):
        return False


def request_with_retry(
    make_request: Callable[[], urllib.request.Request],
    *,
    stop_event: threading.Event,
    item: ItemControl | None = None,
    limiter: RateLimiter | None = None,
    policy: RetryPolicy | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    log: Callable[[str], None] | None = None,
    label: str = "request",
):
    """
    Open a request, retrying 429/5xx/network errors with backoff (honouring `Retry-After`).
    Raises LinkExpiredError on 401/403/410 and DownloadFailed on other HTTP errors.
    """
    policy = policy or RetryPolicy()
    attempt = 0
    while True:
        attempt += 1
        check_stop(stop_event, item)
        if limiter:
            limiter.before_request()
        try:
            req = make_request()
            if req.type != "https" and not _allow_http(req.host):
                raise DownloadFailed(f"{label}: refusing non-https URL")
            # Scheme is checked above: https only, plain http for loopback test servers.
            return urllib.request.urlopen(req, timeout=timeout)  # nosec B310
        except urllib.error.HTTPError as e:
            if e.code in EXPIRED_STATUS:
                raise LinkExpiredError(e.code) from None
            if e.code in TRANSIENT_STATUS and attempt < policy.max_attempts:
                delay = policy.backoff(attempt, parse_retry_after(e.headers.get("Retry-After") if e.headers else None))
                if log:
                    log(f"{label}: HTTP {e.code}, retrying in {delay:.1f}s ({attempt}/{policy.max_attempts - 1})")
                interruptible_sleep(delay, stop_event, item)
                continue
            detail = ""
            try:
                body = e.read(600)
                if body:
                    detail = ": " + redact_text(body.decode("utf-8", "replace")).strip()[:300]
            except Exception:
                pass
            raise DownloadFailed(f"{label}: HTTP {e.code}{detail}") from None
        except TRANSIENT_ERRORS as e:
            if attempt >= policy.max_attempts:
                raise DownloadFailed(f"{label}: network error after {attempt} attempts: {e}") from None
            delay = policy.backoff(attempt)
            if log:
                log(f"{label}: network error ({e.__class__.__name__}), retrying in {delay:.1f}s")
            interruptible_sleep(delay, stop_event, item)


def download_with_progress(
    url: str,
    dest_path: Path,
    *,
    stop_event: threading.Event,
    q: queue.Queue,
    item_id: str | None = None,
    item: ItemControl | None = None,
    limiter: RateLimiter | None = None,
    policy: RetryPolicy | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    validate_zip: bool | None = None,
    throttle: EventThrottle | None = None,
) -> str:
    """
    Resumable download to `dest_path` via `<dest>.part`. Returns "downloaded" or "skipped".

    The `.part` file is kept when the link expires, the user stops/cancels, or the
    network keeps failing, so the next run resumes with an HTTP Range request.
    """
    policy = policy or RetryPolicy()
    throttle = throttle or EventThrottle(0.25)
    validate_zip = dest_path.suffix.lower() == ".zip" if validate_zip is None else validate_zip
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_name(dest_path.name + ".part")

    def log(message: str) -> None:
        post_event(q, "log", message=message)

    def progress(percent: int, downloaded: int, total: int | None, rate: float, force: bool = False) -> None:
        if item_id and throttle.ready(item_id, force=force):
            post_event(
                q,
                "item_progress",
                id=item_id,
                percent=percent,
                bytes=downloaded,
                total_bytes=total,
                rate_mb_s=rate,
            )

    if dest_path.exists() and dest_path.stat().st_size > 0:
        if not validate_zip or zip_is_readable(dest_path):
            size = dest_path.stat().st_size
            progress(100, size, size, 0.0, force=True)
            log(f"Already downloaded: {dest_path.name}")
            return "skipped"
        dest_path.unlink(missing_ok=True)

    attempt = 0
    while True:
        attempt += 1
        resume_offset = part_path.stat().st_size if part_path.exists() else 0

        def make_request(offset: int = resume_offset) -> urllib.request.Request:
            h = {"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
            if offset > 0:
                h["Range"] = f"bytes={offset}-"
            return urllib.request.Request(url, headers=h)

        try:
            resp = request_with_retry(
                make_request,
                stop_event=stop_event,
                item=item,
                limiter=limiter,
                policy=policy,
                timeout=timeout,
                log=log,
                label=dest_path.name,
            )
        except DownloadFailed as e:
            if "HTTP 416" in str(e) and resume_offset > 0:
                # The part file is larger than the remote file: start over.
                part_path.unlink(missing_ok=True)
                continue
            raise

        try:
            with resp:
                status = getattr(resp, "status", None) or resp.getcode()
                length_hdr = resp.headers.get("Content-Length")
                remaining = int(length_hdr) if length_hdr and length_hdr.isdigit() else None
                total_bytes: int | None = None
                content_range = resp.headers.get("Content-Range")
                if content_range and "/" in content_range:
                    tail = content_range.rsplit("/", 1)[1].strip()
                    total_bytes = int(tail) if tail.isdigit() else None

                if resume_offset > 0 and status != 206:
                    # Server ignored Range: restart from zero.
                    resume_offset = 0
                    total_bytes = remaining
                elif resume_offset == 0:
                    total_bytes = total_bytes or remaining

                downloaded = resume_offset
                window_start = time.monotonic()
                window_bytes = downloaded
                with open(part_path, "ab" if resume_offset > 0 else "wb") as f:
                    while True:
                        check_stop(stop_event, item)
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if limiter:
                            limiter.consume(len(chunk))
                        now = time.monotonic()
                        if now - window_start >= 0.5:
                            rate = (downloaded - window_bytes) / (now - window_start) / (1024 * 1024)
                            percent = int(downloaded * 100 / total_bytes) if total_bytes else 0
                            progress(max(0, min(100, percent)), downloaded, total_bytes, rate)
                            window_start, window_bytes = now, downloaded

            if total_bytes is not None and downloaded < total_bytes:
                raise http.client.IncompleteRead(b"", total_bytes - downloaded)
        except TRANSIENT_ERRORS as e:
            if attempt >= policy.max_attempts:
                raise DownloadFailed(f"{dest_path.name}: connection kept dropping ({e.__class__.__name__}); partial file kept") from None
            delay = policy.backoff(attempt)
            log(f"{dest_path.name}: connection dropped, resuming in {delay:.1f}s")
            interruptible_sleep(delay, stop_event, item)
            continue
        break

    if validate_zip and not zip_is_readable(part_path):
        part_path.unlink(missing_ok=True)
        raise DownloadFailed(f"{dest_path.name}: downloaded file is not a valid ZIP")

    part_path.replace(dest_path)
    size = dest_path.stat().st_size
    progress(100, size, size, 0.0, force=True)
    log(f"Downloaded: {dest_path.name}")
    return "downloaded"
