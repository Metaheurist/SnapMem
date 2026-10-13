import pytest

from sc_memories_downloader.urls import (
    get_zip_filename_from_url,
    is_export_zip_url,
    is_snapchat_url,
    load_urls,
    redact_text,
    redact_url,
)

GOOD = "https://storage.googleapis.com/snap-export/mydata~1700000000000.zip?X-Goog-Signature=abc"


@pytest.mark.parametrize(
    "url",
    [
        GOOD,
        "https://STORAGE.googleapis.com/bucket/mydata~2.zip",
        "  https://storage.googleapis.com/b/mydata~3.zip  ",
    ],
)
def test_export_zip_url_accepts_snapchat_bucket(url):
    assert is_export_zip_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://storage.googleapis.com/b/mydata~1.zip",
        "https://storage.googleapis.com.evil.example/b/mydata~1.zip",
        "https://evil.example/storage.googleapis.com/mydata~1.zip",
        "https://storage.googleapis.com@evil.example/mydata~1.zip",
        "https://evil.example/?u=https://storage.googleapis.com/mydata~1.zip",
        "https://storage.googleapis.com/b/other.zip",
        "https://storage.googleapis.com/b/mydata~1.zip.exe",
        "javascript:alert(1)",
        "",
    ],
)
def test_export_zip_url_rejects_lookalikes(url):
    assert not is_export_zip_url(url)


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://app.snapchat.com/dmd/memories?mid=1", True),
        ("https://snapchat.com/x", True),
        ("http://app.snapchat.com/dmd", False),
        ("https://evilsnapchat.com/dmd", False),
        ("https://snapchat.com.evil.example/dmd", False),
    ],
)
def test_is_snapchat_url(url, ok):
    assert is_snapchat_url(url) is ok


def test_zip_filename_from_url():
    assert get_zip_filename_from_url(GOOD) == "mydata~1700000000000.zip"
    assert get_zip_filename_from_url("https://storage.googleapis.com/") == "download.zip"


def test_redaction_hides_signed_query():
    assert redact_url(GOOD) == "https://storage.googleapis.com/snap-export/mydata~1700000000000.zip?<redacted>"
    assert redact_url("https://example.com/a") == "https://example.com/a"
    text = f"Request {GOOD} failed; retry https://app.snapchat.com/dmd?sig=zzz"
    out = redact_text(text)
    assert "abc" not in out and "zzz" not in out
    assert out.count("<redacted>") == 2
    loose = redact_text("<Error>bad X-Goog-Signature=abcd&uid=me token=t1</Error>")
    assert "abcd" not in loose and "me" not in loose.replace("<redacted>", "") and "t1" not in loose


def test_load_urls_skips_blank_and_comments(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text(f"# comment\n\n{GOOD}\n  https://x.example/y \n", encoding="utf-8")
    assert load_urls(f) == [GOOD, "https://x.example/y"]
    assert load_urls(tmp_path / "missing.txt") == []
