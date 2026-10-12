import queue
import threading
import zipfile

import pytest

from sc_memories_downloader.extract import is_within, safe_extract_zip
from tests.conftest import drain


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_extracts_normal_entries(tmp_path):
    z = _zip(tmp_path / "a.zip", {"memories/one.jpg": b"1", "json/memories_history.json": b"{}"})
    out = tmp_path / "out"
    n = safe_extract_zip(z, out, threading.Event(), queue.Queue())
    assert n == 2
    assert (out / "memories" / "one.jpg").read_bytes() == b"1"


@pytest.mark.parametrize("evil", ["../escape.txt", "../../escape.txt", "memories/../../escape.txt", "/abs.txt", "C:/win.txt", "..\\back.txt"])
def test_blocks_zip_slip(tmp_path, evil):
    z = _zip(tmp_path / "a.zip", {evil: b"pwned", "ok.jpg": b"1"})
    out = tmp_path / "nested" / "out"
    q = queue.Queue()
    n = safe_extract_zip(z, out, threading.Event(), q)
    assert n == 1
    assert (out / "ok.jpg").exists()
    assert not any(p.name in {"escape.txt", "abs.txt", "win.txt", "back.txt"} for p in tmp_path.rglob("*") if p.is_file() and out not in p.parents)
    assert any("Skipped unsafe path" in e.get("message", "") for e in drain(q))


def test_prefix_sibling_is_not_inside(tmp_path):
    base = tmp_path / "out"
    assert is_within(base, base / "a")
    assert not is_within(base, tmp_path / "out-evil" / "a")


def test_cancel_stops_extraction(tmp_path):
    z = _zip(tmp_path / "a.zip", {"a.jpg": b"1"})
    stop = threading.Event()
    stop.set()
    with pytest.raises(RuntimeError, match="Cancelled"):
        safe_extract_zip(z, tmp_path / "out", stop, queue.Queue())
