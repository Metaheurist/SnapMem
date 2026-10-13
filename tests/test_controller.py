import time

from sc_memories_downloader.app.controller import AppController
from sc_memories_downloader.events import post_event
from sc_memories_downloader.main import StartupOptions
from sc_memories_downloader.sample import build_sample_export
from sc_memories_downloader.settings import Settings


def _ctrl(tmp_path, **opts):
    return AppController(StartupOptions(output_dir=str(tmp_path / "out"), **opts), settings=Settings())


def test_startup_options_apply(tmp_path):
    z = build_sample_export(tmp_path / "src", count=2)
    c = _ctrl(tmp_path, urls=["https://storage.googleapis.com/b/mydata~1.zip"], import_paths=[z], write_urls_file=True)
    assert c.settings.output_dir == str(tmp_path / "out")
    assert c.settings.write_urls_file is True
    assert c.selection.zip_files == [z.resolve()]
    assert c.can_start


def test_cannot_start_without_input(tmp_path):
    c = _ctrl(tmp_path)
    assert not c.can_start
    assert c.start() is False


def test_event_mapping(tmp_path):
    c = _ctrl(tmp_path)
    q = c.q
    post_event(q, "log", message="hello")
    post_event(q, "item_added", id="a", title="A", kind="zip_file")
    post_event(q, "item_stage", id="a", stage="extract")
    post_event(q, "item_progress", id="a", percent=50, bytes=10, total_bytes=20)
    changed = c.drain()
    assert changed == {"logs", "items", "status"}
    item = c.items["a"]
    assert (item.stage, item.percent, item.bytes, item.total_bytes) == ("extract", 50, 10, 20)
    assert item.overall_fraction == 0.25

    post_event(q, "item_state", id="a", state="done", detail="ok")
    post_event(q, "links_found", urls=["u1", "u2"])
    post_event(q, "auth_state", state="running", detail="waiting")
    assert c.drain() == {"items", "status", "links", "auth"}
    assert item.percent == 100 and c.overall == 1.0
    assert c.urls == ["u1", "u2"] and c.auth_running

    post_event(q, "links_expired", id="a")
    post_event(q, "done", ok=True, message="Finished", summary={"media": 3})
    version = c.library_version
    assert "library" in c.drain()
    assert c.links_expired and not c.running
    assert c.last_result["ok"] and c.library_version == version + 1

    post_event(q, "unknown")
    post_event(q, "item_progress", id="missing", percent=5)
    assert c.drain() == set()


def test_pause_is_not_overridden_by_running_event(tmp_path):
    c = _ctrl(tmp_path)
    post_event(c.q, "item_added", id="a", title="A", kind="zip_url")
    c.drain()
    from sc_memories_downloader.download import ItemControl

    c.controls["a"] = ItemControl()
    c.items["a"].state = "running"
    c.toggle_pause("a")
    assert c.items["a"].state == "paused" and c.controls["a"].paused.is_set()
    post_event(c.q, "item_state", id="a", state="running")
    c.drain()
    assert c.items["a"].state == "paused"
    c.toggle_pause("a")
    assert c.items["a"].state == "running" and not c.controls["a"].paused.is_set()
    c.stop_item("a")
    assert c.controls["a"].stopped.is_set()


def test_full_job_through_controller(tmp_path):
    z = build_sample_export(tmp_path / "src", count=6)
    c = _ctrl(tmp_path, import_paths=[z])
    assert c.start()
    deadline = time.monotonic() + 30
    while c.running and time.monotonic() < deadline:
        c.drain()
        time.sleep(0.05)
    c.drain()
    assert not c.running
    assert c.last_result["ok"], c.last_result
    assert len([r for r in c.library() if r.kind != "overlay"]) == 6
    assert c.clear_previous_data()
    assert c.library() == []


def test_update_settings_persists(tmp_path, isolated_home):
    c = _ctrl(tmp_path)
    c.update_settings(Settings(layout="flat", max_zip_downloads=50))
    assert c.settings.max_zip_downloads == 6
    assert (isolated_home / "settings.json").is_file()
