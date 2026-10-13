# apps/renderer/tests/conftest.py

"""Linux-only fixtures: a local signed-URL stand-in and driver configuration."""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from driver.isolation import make_driver_undumpable
from driver.server import DriverConfig

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config: pytest.Config) -> None:
    # The driver kills every other process under its user between requests.
    if os.environ.get("RENDERER_TEST_CONTAINER") != "1":
        pytest.exit("Run renderer tests in Docker: make media-renderer-check", returncode=2)


class FakeStorage(ThreadingHTTPServer):
    """Serves fixtures and keeps uploaded bodies."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _StorageHandler)
        self.objects: dict[str, bytes] = {
            path.name: path.read_bytes() for path in FIXTURES.iterdir()
        }
        self.uploads: dict[str, bytes] = {}
        self.requests: list[tuple[str, str, str | None]] = []

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def source(self, name: str) -> dict:
        return {
            "url": f"{self.base_url}objects/{name}",
            "headers": {},
            "size_bytes": len(self.objects[name]),
        }

    def target(self, name: str) -> dict:
        return {
            "url": f"{self.base_url}uploads/{name}",
            "headers": {"content-type": "application/octet-stream"},
        }


class _StorageHandler(BaseHTTPRequestHandler):
    server: FakeStorage

    def do_GET(self) -> None:
        self.server.requests.append(("GET", self.path, self.headers.get("range")))
        data = self.server.objects.get(self.path.removeprefix("/objects/"))
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self) -> None:
        self.server.requests.append(("PUT", self.path, None))
        length = int(self.headers["content-length"])
        self.server.uploads[self.path.removeprefix("/uploads/")] = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args) -> None:
        return


@pytest.fixture(scope="session", autouse=True)
def undumpable_driver() -> None:
    # The test process plays the driver, so it needs the driver's protection too.
    make_driver_undumpable()


@pytest.fixture
def storage():
    server = FakeStorage()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def config(storage: FakeStorage) -> DriverConfig:
    return DriverConfig(
        allowed_url_prefixes=(storage.base_url,),
        max_input_bytes=64 * 1024 * 1024,
        max_output_bytes=64 * 1024 * 1024,
        max_timeout_seconds=120,
        child_memory_bytes=2 * 1024**3,
    )
