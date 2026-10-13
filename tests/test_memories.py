import json
import threading
from datetime import datetime, timezone

import pytest

from sc_memories_downloader import memories
from sc_memories_downloader.download import DownloadFailed
from sc_memories_downloader.memories import (
    MemoryEntry,
    build_id_index,
    find_uuid,
    load_memories,
    parse_date,
    parse_location,
    resolve_cdn_url,
)

MID = "AAAAAAAA-1111-4222-8333-944455556666"


def test_parse_date_and_location():
    assert parse_date("2023-05-01 18:22:05 UTC") == datetime(2023, 5, 1, 18, 22, 5, tzinfo=timezone.utc)
    assert parse_date("yesterday") is None
    assert parse_location("Latitude, Longitude: 51.5, -0.12") == (51.5, -0.12)
    assert parse_location("Latitude, Longitude: 0.0, 0.0") == (None, None)
    assert parse_location(None) == (None, None)


def test_load_memories_and_index(tmp_path):
    f = tmp_path / "memories_history.json"
    f.write_text(
        json.dumps(
            {
                "Saved Media": [
                    {"Date": "2023-05-01 18:22:05 UTC", "Media Type": "Video", "Location": "Latitude, Longitude: 1.5, 2.5", "Download Link": f"https://app.snapchat.com/dmd/memories?uid=u&sid={MID}&mid={MID}&sig=s"},
                    {"Date": "bad", "Media Type": "Image"},
                    "junk",
                    {"Date": "2022-01-01 00:00:00 UTC", "Media Type": "Image", "Media Download Url": "https://app.snapchat.com/x?mid=other"},
                ]
            }
        ),
        encoding="utf-8",
    )
    entries = load_memories(f)
    assert len(entries) == 2
    assert entries[0].kind == "video" and entries[0].latitude == 1.5
    assert entries[0].ids == {MID.lower()}
    assert entries[1].download_link.endswith("mid=other")
    index = build_id_index(entries)
    assert index[MID.lower()] is entries[0]
    assert find_uuid(f"2023-05-01_{MID}-main.mp4") == MID.lower()
    assert find_uuid("no-id.jpg") is None


def test_resolve_cdn_url_posts_form(server, monkeypatch, fast_policy):
    monkeypatch.setattr(memories, "is_snapchat_url", lambda u: True)
    route = server.add("/dmd/memories", post_body=b"https://cdn.example/file.jpg")
    entry = MemoryEntry(datetime.now(timezone.utc), "Image", server.url("/dmd/memories?mid=1&sig=2"))
    assert resolve_cdn_url(entry, stop_event=threading.Event(), policy=fast_policy) == "https://cdn.example/file.jpg"
    hit = route.hits[0]
    assert hit["method"] == "POST"
    assert hit["data"] == b"mid=1&sig=2"
    assert hit["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_resolve_cdn_url_rejects_unexpected_body(server, monkeypatch, fast_policy):
    monkeypatch.setattr(memories, "is_snapchat_url", lambda u: True)
    server.add("/dmd/memories", post_body=b"<html>login</html>")
    entry = MemoryEntry(datetime.now(timezone.utc), "Image", server.url("/dmd/memories?mid=1"))
    with pytest.raises(DownloadFailed):
        resolve_cdn_url(entry, stop_event=threading.Event(), policy=fast_policy)


def test_resolve_cdn_url_requires_snapchat_host():
    entry = MemoryEntry(datetime.now(timezone.utc), "Image", "https://evil.example/dmd?mid=1")
    with pytest.raises(DownloadFailed, match="snapchat.com"):
        resolve_cdn_url(entry, stop_event=threading.Event())
