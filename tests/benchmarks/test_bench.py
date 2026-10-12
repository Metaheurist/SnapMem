import os
import queue
import shutil
import threading
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from sc_memories_downloader.extract import safe_extract_zip
from sc_memories_downloader.organize import Organizer, load_library
from sc_memories_downloader.ratelimit import RateLimiter

FILES = 400


@pytest.fixture(scope="module")
def big_zip(tmp_path_factory):
    path = tmp_path_factory.mktemp("bench") / "mydata~bench.zip"
    payload = os.urandom(32 * 1024)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for i in range(FILES):
            zf.writestr(f"memories/2023-01-01_{i:05d}-main.jpg", payload)
    return path


def test_extract(benchmark, big_zip, tmp_path):
    def run():
        out = tmp_path / "out"
        shutil.rmtree(out, ignore_errors=True)
        return safe_extract_zip(big_zip, out, threading.Event(), queue.Queue())

    assert benchmark.pedantic(run, rounds=5, iterations=1) == FILES


def test_organize(benchmark, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)

    def setup():
        shutil.rmtree(tmp_path / "media", ignore_errors=True)
        for i in range(FILES):
            (src / f"{start + timedelta(hours=i):%Y-%m-%d_%H-%M-%S}_{i}.jpg").write_bytes(i.to_bytes(4, "big") * 64)
        return (), {}

    def run():
        org = Organizer(tmp_path / "media", mode="move")
        org.organize_tree(src)
        org.write_index()
        return org.placed

    assert benchmark.pedantic(run, setup=setup, rounds=5, iterations=1) == FILES


def test_load_library(benchmark, tmp_path):
    org = Organizer(tmp_path / "media", mode="move")
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    for i in range(FILES):
        p = tmp_path / f"{i}.jpg"
        p.write_bytes(i.to_bytes(4, "big"))
        org.place(p, dt=start + timedelta(hours=i))
    org.write_index()
    assert len(benchmark(load_library, tmp_path / "media")) == FILES


def test_rate_limiter_overhead(benchmark):
    rl = RateLimiter(bytes_per_sec=10**12, min_gap=0)

    def run():
        for _ in range(10_000):
            rl.consume(256 * 1024)

    benchmark(run)
