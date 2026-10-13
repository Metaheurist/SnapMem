import re
import urllib.parse
from pathlib import Path

EXPORT_ZIP_HOST = "storage.googleapis.com"
SNAPCHAT_DOMAIN = "snapchat.com"

_URL_QUERY_RE = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*")
_SECRET_PARAM_RE = re.compile(r"(?i)\b(sig|signature|x-goog-signature|x-goog-credential|token|key|uid)=[^&\s\"'<>]+")


def get_zip_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name
    return name if name else "download.zip"


def is_export_zip_url(url: str) -> bool:
    """True for an https `mydata~*.zip` link served from the Snapchat export bucket."""
    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != EXPORT_ZIP_HOST:
        return False
    name = get_zip_filename_from_url(url)
    return name.startswith("mydata~") and name.endswith(".zip")


def is_snapchat_url(url: str) -> bool:
    """True for an https URL on snapchat.com or one of its subdomains."""
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == SNAPCHAT_DOMAIN or host.endswith("." + SNAPCHAT_DOMAIN))


def redact_url(url: str) -> str:
    """Drop the query string so signed parameters never reach logs."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return "<invalid url>"
    if not parsed.query:
        return url
    return urllib.parse.urlunparse(parsed._replace(query="<redacted>", fragment=""))


def redact_text(text: str) -> str:
    """Redact URL query strings and loose signature parameters found in free text (server error bodies)."""
    return _SECRET_PARAM_RE.sub(r"\1=<redacted>", _URL_QUERY_RE.sub(r"\1?<redacted>", text))


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
