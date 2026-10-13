import io
import json
import queue
import threading
import zipfile

from sc_memories_downloader.organize import read_index
from sc_memories_downloader.paths import get_script_paths
from sc_memories_downloader.sample import _jpeg_bytes, _mp4_bytes, build_sample_export
from sc_memories_downloader.settings import Settings
from sc_memories_downloader.worker import EXPIRED_STREAK_LIMIT, Job, JobRunner, plan_items, sniff_suffix
from tests.conftest import drain

UIDS = [f"00000000-0000-4000-8000-00000000000{i}" for i in range(1, 10)]


def _run(tmp_path, job, policy=None, **settings):
    q = queue.Queue()
    s = Settings(output_dir=str(tmp_path / "out"), min_request_gap_ms=0, **settings)
    summary = JobRunner(job, s, q, threading.Event(), policy=policy).run()
    return summary, drain(q), get_script_paths(s.output_dir)


def test_plan_items_ids():
    from pathlib import Path

    job = Job(zip_urls=["https://storage.googleapis.com/b/mydata~1.zip"], zip_files=[Path("a.zip")], export_dirs=[Path("d")], memories_json=Path("m.json"))
    assert [i.id for i in plan_items(job)] == ["url:mydata~1.zip", "zip:a.zip", "dir:d", "memories"]


def test_zip_import_end_to_end(tmp_path):
    z = build_sample_export(tmp_path / "src", count=8)
    summary, events, paths = _run(tmp_path, Job(zip_files=[z]))
    assert summary["done"] == 1 and summary["failed"] == 0
    done = [e for e in events if e["type"] == "done"][-1]
    assert done["ok"]
    files = sorted(p.relative_to(paths.media_dir).as_posix() for p in paths.media_dir.rglob("*") if p.suffix in {".jpg", ".mp4", ".png"})
    assert files[0].startswith("2023/01/2023-01-14_09-30-00_")
    assert len(read_index(paths.media_dir)) == len(files) == 10
    assert not (tmp_path / "escape.txt").exists()


def test_export_folder_is_copied_not_moved(tmp_path):
    root = tmp_path / "export" / "memories"
    root.mkdir(parents=True)
    (root / f"2022-02-02_{UIDS[0]}-main.jpg").write_bytes(_jpeg_bytes((1, 2, 3)))
    summary, _, paths = _run(tmp_path, Job(export_dirs=[tmp_path / "export"]), file_mode="move")
    assert summary["done"] == 1
    assert (root / f"2022-02-02_{UIDS[0]}-main.jpg").exists()
    assert any(paths.media_dir.rglob("2022-02-02_*_photo.jpg"))


def _memories_json(tmp_path, server, entries):
    data = {"Saved Media": []}
    for i, (kind, path) in enumerate(entries):
        data["Saved Media"].append(
            {
                "Date": f"2024-03-0{i + 1} 10:00:00 UTC",
                "Media Type": kind,
                "Location": "Latitude, Longitude: 10.0, 20.0",
                "Download Link": server.url(f"{path}?uid=u&mid={UIDS[i]}&sig=s"),
            }
        )
    f = tmp_path / "memories_history.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def test_memories_download_with_fallback_and_resume(tmp_path, server, fast_policy):
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("main.jpg", _jpeg_bytes((9, 9, 9)))
        zf.writestr("x-overlay.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    routes = [
        server.add("/m/1", body=_jpeg_bytes((200, 10, 10))),
        server.add("/m/2", body=_mp4_bytes()),
        server.add("/m/3", body=bundle.getvalue()),
    ]
    f = _memories_json(tmp_path, server, [("Image", "/m/1"), ("Video", "/m/2"), ("Image", "/m/3")])
    summary, events, paths = _run(tmp_path, Job(memories_json=f), policy=fast_policy)
    assert summary["done"] == 1, events
    names = sorted(p.name for p in paths.media_dir.rglob("*") if p.is_file() and p.name != "library.json")
    assert names == [
        "2024-03-01_10-00-00_photo.jpg",
        "2024-03-02_10-00-00_video.mp4",
        "2024-03-03_10-00-00_overlay.png",
        "2024-03-03_10-00-00_photo.jpg",
    ]
    for r in routes:
        assert r.hits[-1]["headers"].get("X-Snap-Route-Tag") == "mem-dmd"
    assert read_index(paths.media_dir)[0].latitude == 10.0

    hits_before = sum(len(r.hits) for r in routes)
    summary, _, _ = _run(tmp_path, Job(memories_json=f), policy=fast_policy)
    assert summary["done"] == 1
    assert sum(len(r.hits) for r in routes) == hits_before


def test_memories_expired_links(tmp_path, server, fast_policy):
    entries = []
    for i in range(EXPIRED_STREAK_LIMIT + 1):
        server.add(f"/e/{i}", fail_with=[403, 403, 403])
        entries.append(("Image", f"/e/{i}"))
    f = _memories_json(tmp_path, server, entries)
    summary, events, _ = _run(tmp_path, Job(memories_json=f), policy=fast_policy, max_memory_downloads=1)
    assert summary["expired"] == 1
    assert any(e["type"] == "links_expired" for e in events)
    assert [e for e in events if e["type"] == "done"][-1]["ok"] is False


def test_zip_url_job_downloads_extracts_and_sorts(tmp_path, server, fast_policy, monkeypatch):
    from sc_memories_downloader import worker

    z = build_sample_export(tmp_path / "src", count=3)
    server.add("/b/mydata~1.zip", body=z.read_bytes())
    monkeypatch.setattr(worker, "is_export_zip_url", lambda u: True)
    summary, events, paths = _run(tmp_path, Job(zip_urls=[server.url("/b/mydata~1.zip")]), policy=fast_policy)
    assert summary["done"] == 1, events
    assert (paths.downloads_dir / "mydata~1.zip").exists()
    assert len(read_index(paths.media_dir)) == 4


def test_zip_url_job_refuses_other_hosts(tmp_path, server, fast_policy):
    server.add("/b/mydata~1.zip", body=b"x")
    summary, _, _ = _run(tmp_path, Job(zip_urls=[server.url("/b/mydata~1.zip")]), policy=fast_policy)
    assert summary["failed"] == 1


def test_sniff_suffix(tmp_path):
    cases = {
        b"PK\x03\x04rest": ".zip",
        b"\xff\xd8\xff\xe0": ".jpg",
        b"\x89PNG\r\n": ".png",
        b"\x00\x00\x00\x18ftypmp42": ".mp4",
        b"RIFF\x00\x00\x00\x00WEBP": ".webp",
    }
    for head, suffix in cases.items():
        p = tmp_path / "f.bin"
        p.write_bytes(head + b"0" * 16)
        assert sniff_suffix(p, "photo") == suffix
    p.write_bytes(b"unknown data here")
    assert sniff_suffix(p, "video") == ".mp4"
    assert sniff_suffix(p, "photo") == ".jpg"
