import json
import os
from datetime import datetime, timezone

import pytest

from sc_memories_downloader.memories import MemoryEntry
from sc_memories_downloader.organize import (
    INDEX_NAME,
    Organizer,
    capture_info,
    date_from_name,
    kind_of,
    load_library,
    read_index,
    rebuild_index,
    reorganize_library,
    target_name,
)

UID = "0f8a7c2e-1111-4222-8333-944455556666"
DT = datetime(2023, 5, 1, 18, 22, 5, tzinfo=timezone.utc)


def _write(path, data=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.mark.parametrize(
    "layout,expected",
    [
        ("year_month", "2023/05/2023-05-01_18-22-05_photo.jpg"),
        ("year", "2023/2023-05-01_18-22-05_photo.jpg"),
        ("flat", "2023-05-01_18-22-05_photo.jpg"),
    ],
)
def test_layouts(tmp_path, layout, expected):
    src = _write(tmp_path / "in" / "x.jpg")
    media = tmp_path / "media"
    dest = Organizer(media, layout=layout).place(src, dt=DT)
    assert dest.relative_to(media).as_posix() == expected
    assert not src.exists()


def test_copy_mode_keeps_source(tmp_path):
    src = _write(tmp_path / "in" / "x.jpg")
    Organizer(tmp_path / "media", mode="copy").place(src, dt=DT)
    assert src.exists()


def test_sets_file_time_to_capture_date(tmp_path):
    src = _write(tmp_path / "in" / "x.jpg")
    dest = Organizer(tmp_path / "media").place(src, dt=DT)
    assert int(os.stat(dest).st_mtime) == int(DT.timestamp())


def test_name_clash_gets_numbered(tmp_path):
    media = tmp_path / "media"
    org = Organizer(media)
    a = org.place(_write(tmp_path / "in" / "a.jpg", b"A"), dt=DT)
    b = org.place(_write(tmp_path / "in" / "b.jpg", b"B"), dt=DT)
    assert a.name == "2023-05-01_18-22-05_photo.jpg"
    assert b.name == "2023-05-01_18-22-05_photo_2.jpg"
    assert org.placed == 2


def test_same_content_is_not_duplicated(tmp_path):
    media = tmp_path / "media"
    org = Organizer(media)
    org.place(_write(tmp_path / "in" / "a.jpg", b"same"), dt=DT)
    org.place(_write(tmp_path / "in2" / "a.jpg", b"same"), dt=DT)
    files = [p for p in media.rglob("*.jpg")]
    assert len(files) == 1
    assert org.skipped == 1


def test_overlay_and_video_kinds(tmp_path):
    assert kind_of(tmp_path / "2023-05-01_x-overlay.png") == "overlay"
    assert kind_of(tmp_path / "clip.MP4") == "video"
    assert kind_of(tmp_path / "pic.jpeg") == "photo"
    assert target_name(DT, "video", ".MP4") == "2023-05-01_18-22-05_video.mp4"


def test_capture_date_priority(tmp_path):
    entry = MemoryEntry(date=DT, media_type="Video", download_link=f"https://app.snapchat.com/dmd/memories?mid={UID}")
    named = _write(tmp_path / f"2020-01-02_{UID}-main.mp4")
    dt, matched = capture_info(named, {UID: entry})
    assert dt == DT and matched is entry

    dt, matched = capture_info(named, {})
    assert dt == datetime(2020, 1, 2, tzinfo=timezone.utc) and matched is None

    plain = _write(tmp_path / "IMG.jpg")
    os.utime(plain, (1_600_000_000, 1_600_000_000))
    dt, _ = capture_info(plain)
    assert dt == datetime.fromtimestamp(1_600_000_000, tz=timezone.utc)


def test_date_from_name_variants():
    assert date_from_name("2023-05-01_18-22-05_photo.jpg") == DT
    assert date_from_name("2023-05-01_abc.jpg") == datetime(2023, 5, 1, tzinfo=timezone.utc)
    assert date_from_name("2023-13-01.jpg") is None
    assert date_from_name("photo.jpg") is None


def test_memory_entry_sets_kind_and_location(tmp_path):
    entry = MemoryEntry(date=DT, media_type="Video", download_link="", latitude=51.5, longitude=-0.12)
    org = Organizer(tmp_path / "media")
    dest = org.place(_write(tmp_path / "in" / "x.bin"), dt=DT, entry=entry)
    assert "_video" in dest.name
    rec = next(iter(org.records.values()))
    assert (rec.latitude, rec.longitude) == (51.5, -0.12)


def test_index_is_written_and_merged(tmp_path):
    media = tmp_path / "media"
    org = Organizer(media)
    org.place(_write(tmp_path / "in" / "a.jpg", b"A"), dt=DT)
    org.write_index()
    org2 = Organizer(media)
    org2.place(_write(tmp_path / "in" / "b.mp4", b"B"), dt=datetime(2024, 1, 1, tzinfo=timezone.utc))
    org2.write_index()
    data = json.loads((media / INDEX_NAME).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert [i["kind"] for i in data["items"]] == ["photo", "video"]


def test_load_library_includes_unindexed_and_drops_missing(tmp_path):
    media = tmp_path / "media"
    org = Organizer(media)
    gone = org.place(_write(tmp_path / "in" / "a.jpg", b"A"), dt=DT)
    org.write_index()
    gone.unlink()
    _write(media / "2024" / "2024-02-03_10-00-00_photo.jpg")
    recs = load_library(media)
    assert [r.path for r in recs] == ["2024/2024-02-03_10-00-00_photo.jpg"]


def test_reorganize_moves_into_new_layout(tmp_path):
    media = tmp_path / "media"
    org = Organizer(media, layout="flat")
    org.place(_write(tmp_path / "in" / "a.jpg", b"A"), dt=DT, entry=MemoryEntry(DT, "Image", "", 1.0, 2.0))
    org.write_index()
    moved = reorganize_library(media, "year_month")
    assert moved == 1
    assert (media / "2023" / "05" / "2023-05-01_18-22-05_photo.jpg").exists()
    rec = read_index(media)[0]
    assert rec.path == "2023/05/2023-05-01_18-22-05_photo.jpg"
    assert rec.latitude == 1.0


def test_reorganize_is_idempotent(tmp_path):
    media = tmp_path / "media"
    org = Organizer(media)
    org.place(_write(tmp_path / "in" / "a.jpg", b"A"), dt=DT)
    org.place(_write(tmp_path / "in" / "b.jpg", b"B"), dt=DT)
    org.write_index()
    before = sorted(p.relative_to(media).as_posix() for p in media.rglob("*.jpg"))
    reorganize_library(media, "year_month")
    after = sorted(p.relative_to(media).as_posix() for p in media.rglob("*.jpg"))
    assert before == after


def test_rebuild_index(tmp_path):
    media = tmp_path / "media"
    _write(media / "2022-03-04_05-06-07_video.mp4")
    rebuild_index(media)
    assert read_index(media)[0].kind == "video"
