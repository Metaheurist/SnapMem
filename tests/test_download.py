import io
import queue
import threading
import time
import zipfile

import pytest

from sc_memories_downloader.download import (
    DownloadFailed,
    DownloadStopSignal,
    ItemControl,
    LinkExpiredError,
    download_with_progress,
    zip_is_readable,
)
from sc_memories_downloader.ratelimit import RetryPolicy
from tests.conftest import drain

BODY = bytes(range(256)) * 4000  # ~1 MB


def _get(server, path, dest, policy, **kw):
    q = queue.Queue()
    result = download_with_progress(server.url(path), dest, stop_event=threading.Event(), q=q, item_id="x", policy=policy, **kw)
    return result, drain(q)


def test_plain_download_and_progress(server, tmp_path, fast_policy):
    server.add("/f.bin", body=BODY)
    dest = tmp_path / "f.bin"
    result, events = _get(server, "/f.bin", dest, fast_policy)
    assert result == "downloaded"
    assert dest.read_bytes() == BODY
    assert not (tmp_path / "f.bin.part").exists()
    final = [e for e in events if e["type"] == "item_progress"][-1]
    assert final["percent"] == 100 and final["bytes"] == len(BODY)


def test_existing_file_is_skipped(server, tmp_path, fast_policy):
    route = server.add("/f.bin", body=BODY)
    dest = tmp_path / "f.bin"
    dest.write_bytes(b"already here")
    result, _ = _get(server, "/f.bin", dest, fast_policy)
    assert result == "skipped"
    assert route.hits == []


def test_resumes_from_part_file_with_range(server, tmp_path, fast_policy):
    route = server.add("/f.bin", body=BODY)
    dest = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(BODY[:300_000])
    _get(server, "/f.bin", dest, fast_policy)
    assert dest.read_bytes() == BODY
    assert route.hits[0]["headers"].get("Range") == "bytes=300000-"


def test_restarts_when_server_ignores_range(server, tmp_path, fast_policy):
    server.add("/f.bin", body=BODY, ignore_range=True)
    dest = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(b"x" * 1000)
    _get(server, "/f.bin", dest, fast_policy)
    assert dest.read_bytes() == BODY


def test_restarts_on_416_when_part_is_too_big(server, tmp_path, fast_policy):
    server.add("/f.bin", body=BODY[:1000])
    dest = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(b"x" * 5000)
    _get(server, "/f.bin", dest, fast_policy)
    assert dest.read_bytes() == BODY[:1000]


def test_resumes_after_connection_drop(server, tmp_path, fast_policy):
    route = server.add("/f.bin", body=BODY, drop_after=200_000)
    dest = tmp_path / "f.bin"
    _get(server, "/f.bin", dest, fast_policy)
    assert dest.read_bytes() == BODY
    assert len(route.hits) == 2
    assert route.hits[1]["headers"]["Range"].startswith("bytes=")


def test_429_honours_retry_after(server, tmp_path):
    server.add("/f.bin", body=BODY, fail_with=[429], fail_headers={"Retry-After": "1"})
    dest = tmp_path / "f.bin"
    started = time.monotonic()
    _, events = _get(server, "/f.bin", dest, RetryPolicy(max_attempts=3, base_delay=0.01))
    assert time.monotonic() - started >= 0.9
    assert dest.read_bytes() == BODY
    assert any("HTTP 429, retrying in 1.0s" in e.get("message", "") for e in events)


def test_5xx_is_retried(server, tmp_path, fast_policy):
    route = server.add("/f.bin", body=BODY, fail_with=[503, 502])
    _get(server, "/f.bin", tmp_path / "f.bin", fast_policy)
    assert len(route.hits) == 3


def test_gives_up_after_max_attempts(server, tmp_path, fast_policy):
    server.add("/f.bin", body=BODY, fail_with=[503, 503, 503, 503])
    with pytest.raises(DownloadFailed, match="HTTP 503"):
        _get(server, "/f.bin", tmp_path / "f.bin", fast_policy)


@pytest.mark.parametrize("code", [401, 403, 410])
def test_expired_link_keeps_part_file(server, tmp_path, fast_policy, code):
    route = server.add("/f.bin", body=BODY, fail_with=[code])
    part = tmp_path / "f.bin.part"
    part.write_bytes(BODY[:1000])
    with pytest.raises(LinkExpiredError):
        _get(server, "/f.bin", tmp_path / "f.bin", fast_policy)
    assert part.read_bytes() == BODY[:1000]
    assert len(route.hits) == 1


def test_error_body_is_redacted(server, tmp_path, fast_policy):
    server.add("/f.bin", fail_with=[400])
    with pytest.raises(DownloadFailed) as exc:
        _get(server, "/f.bin", tmp_path / "f.bin", fast_policy)
    assert "secret-token" not in str(exc.value)


def test_timeout_is_retried_then_fails(server, tmp_path):
    server.add("/slow", body=b"late", delay=1.0)
    with pytest.raises(DownloadFailed, match="network error after 2 attempts"):
        _get(server, "/slow", tmp_path / "slow.bin", RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.01), timeout=0.2)


def test_refuses_plain_http_to_remote_hosts(tmp_path, fast_policy):
    with pytest.raises(DownloadFailed, match="non-https"):
        download_with_progress("http://example.invalid/x.zip", tmp_path / "x.zip", stop_event=threading.Event(), q=queue.Queue(), policy=fast_policy)


@pytest.mark.parametrize("target", ["http://example.invalid/x.zip", "ftp://127.0.0.1/x.zip"])
def test_refuses_redirect_off_https(server, tmp_path, fast_policy, target):
    route = server.add("/f.bin", body=BODY, fail_with=[302], fail_headers={"Location": target})
    with pytest.raises(DownloadFailed, match="redirect to a non-https URL"):
        _get(server, "/f.bin", tmp_path / "f.bin", fast_policy)
    assert len(route.hits) == 1


def test_follows_redirect_to_allowed_url(server, tmp_path, fast_policy):
    server.add("/f.bin", body=BODY, fail_with=[302], fail_headers={"Location": "/f.bin"})
    result, _ = _get(server, "/f.bin", tmp_path / "f.bin", fast_policy)
    assert result == "downloaded"
    assert (tmp_path / "f.bin").read_bytes() == BODY


def test_invalid_zip_is_rejected(server, tmp_path, fast_policy):
    server.add("/mydata~1.zip", body=b"<html>not a zip</html>")
    with pytest.raises(DownloadFailed, match="not a valid ZIP"):
        _get(server, "/mydata~1.zip", tmp_path / "mydata~1.zip", fast_policy)
    assert not (tmp_path / "mydata~1.zip.part").exists()


def test_valid_zip_passes(server, tmp_path, fast_policy):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("memories/a.jpg", b"\xff\xd8\xff" + b"0" * 100)
    server.add("/mydata~1.zip", body=buf.getvalue())
    dest = tmp_path / "mydata~1.zip"
    _get(server, "/mydata~1.zip", dest, fast_policy)
    assert zip_is_readable(dest)


def test_stop_keeps_part_and_raises(server, tmp_path, fast_policy):
    server.add("/f.bin", body=BODY)
    control = ItemControl()
    control.stopped.set()
    with pytest.raises(DownloadStopSignal):
        download_with_progress(server.url("/f.bin"), tmp_path / "f.bin", stop_event=threading.Event(), q=queue.Queue(), item=control, policy=fast_policy)
