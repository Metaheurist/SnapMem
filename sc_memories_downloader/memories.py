"""
`memories_history.json` support.

Shape (Snapchat "Export JSON Files"):

    {"Saved Media": [
        {"Date": "2023-05-01 18:22:05 UTC",
         "Media Type": "Image" | "Video",
         "Location": "Latitude, Longitude: 51.50, -0.12",
         "Download Link": "https://app.snapchat.com/dmd/memories?uid=..&sid=..&mid=..&ts=..&sig=.."},
     ...]}

Each Download Link is POSTed as a form body; the response is a short-lived CDN URL
that is then fetched with GET. Some Memories come back as a ZIP holding the media
and its overlay.
"""

import json
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .download import DEFAULT_TIMEOUT, USER_AGENT, DownloadFailed, ItemControl, request_with_retry
from .ratelimit import RateLimiter, RetryPolicy
from .urls import is_snapchat_url

DATE_FORMAT = "%Y-%m-%d %H:%M:%S UTC"
_LATLON_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


@dataclass
class MemoryEntry:
    date: datetime
    media_type: str
    download_link: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def kind(self) -> str:
        return "video" if self.media_type.lower().startswith("video") else "photo"

    @property
    def ids(self) -> set[str]:
        """Memory/snap ids from the link (`mid`, `sid`), lowercased, for matching files in a ZIP export."""
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.download_link).query)
        except ValueError:
            return set()
        return {v.lower() for key in ("mid", "sid") for v in qs.get(key, []) if v}


def parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError):
        return None


def parse_location(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    m = _LATLON_RE.search(value)
    if not m:
        return None, None
    lat, lon = float(m.group(1)), float(m.group(2))
    if lat == 0.0 and lon == 0.0:
        return None, None
    return lat, lon


def load_memories(json_path: Path) -> list[MemoryEntry]:
    data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    items = data.get("Saved Media", []) if isinstance(data, dict) else []
    out: list[MemoryEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        date = parse_date(str(item.get("Date", "")))
        if date is None:
            continue
        lat, lon = parse_location(item.get("Location"))
        out.append(
            MemoryEntry(
                date=date,
                media_type=str(item.get("Media Type", "Image")),
                download_link=str(item.get("Download Link", "") or item.get("Media Download Url", "")),
                latitude=lat,
                longitude=lon,
            )
        )
    return out


def build_id_index(entries: list[MemoryEntry]) -> dict[str, MemoryEntry]:
    index: dict[str, MemoryEntry] = {}
    for e in entries:
        for i in e.ids:
            index.setdefault(i, e)
    return index


def find_uuid(text: str) -> str | None:
    m = _UUID_RE.search(text)
    return m.group(0).lower() if m else None


def resolve_cdn_url(
    entry: MemoryEntry,
    *,
    stop_event: threading.Event,
    item: ItemControl | None = None,
    limiter: RateLimiter | None = None,
    policy: RetryPolicy | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    log=None,
) -> str:
    """POST the Download Link (form-encoded) and return the CDN URL from the response body."""
    link = entry.download_link
    if not is_snapchat_url(link):
        raise DownloadFailed("Download Link is not an https snapchat.com URL")
    base, _, query = link.partition("?")

    def make_request() -> urllib.request.Request:
        return urllib.request.Request(
            base,
            data=query.encode("ascii", "ignore"),
            method="POST",
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        )

    resp = request_with_retry(
        make_request,
        stop_event=stop_event,
        item=item,
        limiter=limiter,
        policy=policy,
        timeout=timeout,
        log=log,
        label="memory link",
    )
    with resp:
        body = resp.read(8192).decode("utf-8", "replace").strip()
    if not body.startswith("https://"):
        raise DownloadFailed("Snapchat did not return a download URL for this Memory")
    return body
