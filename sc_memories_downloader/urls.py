import urllib.parse
from pathlib import Path
from typing import List


def get_zip_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name
    return name if name else "download.zip"


def load_urls(urls_file: Path) -> list[str]:
    """
    Read one URL per line from `urls_file`, ignoring blanks and `#` comments.
    """
    if not urls_file.exists():
        return []

    raw = urls_file.read_text(encoding="utf-8", errors="replace")
    urls: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        urls.append(s)
    return urls


def load_urls_optional(urls_file: Path, default_file: Path | None = None) -> list[str]:
    """
    Load URLs from `urls_file` if present, otherwise try `default_file` (if provided).
    """
    urls = load_urls(urls_file)
    if urls:
        return urls
    if default_file is None:
        return []
    return load_urls(default_file)

