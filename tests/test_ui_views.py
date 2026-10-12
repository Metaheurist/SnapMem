"""Builds every view against a real controller without starting Flutter."""

import types

import pytest

from sc_memories_downloader.app.controller import AppController
from sc_memories_downloader.app.thumbs import thumbnail
from sc_memories_downloader.app.views.connect import ConnectView
from sc_memories_downloader.app.views.downloads import DownloadsView
from sc_memories_downloader.app.views.library import LibraryView
from sc_memories_downloader.app.views.settings import SettingsView
from sc_memories_downloader.events import post_event
from sc_memories_downloader.main import StartupOptions
from sc_memories_downloader.sample import _jpeg_bytes, build_sample_export
from sc_memories_downloader.settings import Settings

ALL = {"items", "logs", "status", "auth", "links", "library"}


@pytest.fixture
def app(tmp_path):
    z = build_sample_export(tmp_path / "src", count=4)
    ctrl = AppController(StartupOptions(output_dir=str(tmp_path / "out"), import_paths=[z]), settings=Settings())
    calls: list[tuple] = []
    return types.SimpleNamespace(
        ctrl=ctrl,
        picker=None,
        page=types.SimpleNamespace(update=lambda: None, show_dialog=lambda d: calls.append(("dialog", d)), pop_dialog=lambda: None),
        navigate=lambda name: calls.append(("navigate", name)),
        toast=lambda msg: calls.append(("toast", msg)),
        redraw=lambda changed: None,
        calls=calls,
    )


@pytest.mark.parametrize("view_cls", [ConnectView, DownloadsView, LibraryView, SettingsView])
def test_view_builds_and_refreshes(app, view_cls):
    view = view_cls(app)
    assert view.build() is not None
    view.refresh(ALL)


def test_downloads_view_tracks_items(app):
    view = DownloadsView(app)
    view.build()
    post_event(app.ctrl.q, "item_added", id="a", title="A", kind="zip_url")
    post_event(app.ctrl.q, "item_progress", id="a", percent=40, bytes=4 * 1024 * 1024, total_bytes=10 * 1024 * 1024, rate_mb_s=1.5)
    view.refresh(app.ctrl.drain())
    assert list(view.cards) == ["a"]
    assert view.cards["a"].bar.value == 0.4
    post_event(app.ctrl.q, "done", ok=True, message="Finished", summary={})
    view.refresh(app.ctrl.drain())
    assert view.phase.value == "All done"


def test_library_view_groups_by_month(app, tmp_path):
    media = app.ctrl.paths.media_dir
    (media / "2024" / "02").mkdir(parents=True)
    (media / "2024" / "02" / "2024-02-03_10-00-00_photo.jpg").write_bytes(_jpeg_bytes((1, 2, 3)))
    (media / "2023" / "11").mkdir(parents=True)
    (media / "2023" / "11" / "2023-11-01_10-00-00_video.mp4").write_bytes(b"\x00" * 32)
    view = LibraryView(app)
    view.build()
    texts = [getattr(c, "controls", [None])[0] for c in view.content.controls if hasattr(c, "controls")]
    assert len(texts) == 2
    assert "1 photo(s), 1 video(s)" in view.stats.value


def test_settings_view_saves(app, isolated_home):
    view = SettingsView(app)
    view.build()
    view.layout.value = "flat"
    view.rate_limit.value = "abc"
    s = view._collect()
    assert s.layout == "flat" and s.rate_limit_mb_s == 0.0


def test_thumbnail(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(_jpeg_bytes((10, 20, 30), size=600))
    data = thumbnail(p)
    assert data and data.startswith(b"\xff\xd8")
    bad = tmp_path / "b.jpg"
    bad.write_bytes(b"nope")
    assert thumbnail(bad) is None
    assert thumbnail(tmp_path / "missing.jpg") is None
