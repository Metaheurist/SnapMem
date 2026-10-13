import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sc_memories_downloader.ratelimit import RetryPolicy  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep settings and browser profiles out of the real %LOCALAPPDATA%."""
    home = tmp_path / "_home"
    monkeypatch.setenv("SNAPMEM_HOME", str(home))
    return home


@pytest.fixture
def fast_policy():
    return RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.02)


def drain(q: queue.Queue) -> list[dict]:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


@dataclass
class Route:
    body: bytes = b""
    # Statuses served before the body, one per request (e.g. [429, 503]).
    fail_with: list[int] = field(default_factory=list)
    fail_headers: dict[str, str] = field(default_factory=dict)
    status: int = 200
    ignore_range: bool = False
    # Close the connection after this many body bytes on the first successful response.
    drop_after: int | None = None
    delay: float = 0.0
    post_body: bytes | None = None
    hits: list[dict] = field(default_factory=list)


class LocalServer:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                pass

            def _route(self) -> Route | None:
                route = server.routes.get(self.path.split("?", 1)[0])
                if route is None:
                    self.send_error(404)
                    return None
                route.hits.append({"method": self.command, "headers": dict(self.headers), "path": self.path})
                if route.delay:
                    time.sleep(route.delay)
                if route.fail_with:
                    code = route.fail_with.pop(0)
                    self.send_response(code)
                    for k, v in route.fail_headers.items():
                        self.send_header(k, v)
                    body = b"error ?sig=secret-token"
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return None
                return route

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(length) if length else b""
                route = self._route()
                if route is None:
                    return
                route.hits[-1]["data"] = data
                body = route.post_body if route.post_body is not None else route.body
                self.send_response(route.status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                route = self._route()
                if route is None:
                    return
                body = route.body
                start = 0
                rng = self.headers.get("Range")
                if rng and not route.ignore_range and rng.startswith("bytes="):
                    start = int(rng[6:].split("-", 1)[0])
                    if start >= len(body):
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{len(body)}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                else:
                    self.send_response(route.status)
                chunk = body[start:]
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                if route.drop_after is not None:
                    cut, route.drop_after = route.drop_after, None
                    self.wfile.write(chunk[:cut])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.wfile.write(chunk)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def add(self, path: str, **kw) -> Route:
        route = Route(**kw)
        self.routes[path] = route
        return route


@pytest.fixture
def server():
    s = LocalServer()
    s.thread.start()
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()
