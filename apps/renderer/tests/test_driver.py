# apps/renderer/tests/test_driver.py

"""Driver request handling: the operation deadline and the HTTP request boundary."""

import http.client
import json
import threading

import pytest
from driver import transfer
from driver.server import DriverConfig, OperationError, RendererServer, handle_request
from media.operations import OPERATIONS

from tests.conftest import FakeStorage


class _EndlessResponse:
    """A download that keeps sending chunks while the clock moves on."""

    status = 200

    def __init__(self, clock: list[float]) -> None:
        self._clock = clock

    def read(self, size: int) -> bytes:
        self._clock[0] += 61
        return b"\0" * 1024

    def __enter__(self) -> "_EndlessResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_a_progressing_download_stops_at_the_deadline(
    storage: FakeStorage, config: DriverConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = {
        "operation": "probe",
        "timeout_seconds": 60,
        "input": storage.source("sample.mp4"),
        "outputs": [],
        "arguments": {},
    }
    clock = [0.0]
    with monkeypatch.context() as patch:
        # The driver and transfers share the time module, so this moves both clocks.
        patch.setattr(transfer.time, "monotonic", lambda: clock[0])
        patch.setattr(transfer, "_open", lambda request, deadline: _EndlessResponse(clock))
        with pytest.raises(OperationError) as error:
            handle_request(request, config=config, operations=OPERATIONS)

    assert error.value.code == "timeout"
    assert handle_request(request, config=config, operations=OPERATIONS)["ok"] is True


def test_requests_need_the_shared_secret_when_one_is_set(config: DriverConfig) -> None:
    secret = "s" * 32
    server = RendererServer(
        ("127.0.0.1", 0),
        config=DriverConfig(**{**config.__dict__, "shared_secret": secret}),
        operations=OPERATIONS,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        refused = [
            _post(server, {"Authorization": value, "Content-Length": "2"}, b"{}")
            for value in ("", "Bearer " + "t" * 32)
        ]
        accepted = _post(
            server, {"Authorization": f"Bearer {secret}", "Content-Length": "2"}, b"{}"
        )
        malformed = _post(server, {"Authorization": f"Bearer {secret}", "Content-Length": "ten"})
    finally:
        server.shutdown()
        server.server_close()

    assert [(status, body["error"]["code"]) for status, body in refused] == [
        (401, "unauthorized"),
        (401, "unauthorized"),
    ]
    # Past authentication, both reach validation; a bad Content-Length gets a structured error.
    for status, body in (accepted, malformed):
        assert (status, body["error"]["code"]) == (400, "invalid_request")


def _post(server: RendererServer, headers: dict[str, str], body: bytes = b"") -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    connection.putrequest("POST", "/v1/operations")
    for name, value in headers.items():
        connection.putheader(name, value)
    connection.endheaders(body or None)
    response = connection.getresponse()
    return response.status, json.loads(response.read())
